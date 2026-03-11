from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import time
from urllib.parse import urlsplit
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel

from ..addons.registry import AddonRegistry, list_addons
from ..system.audit import AuditLogStore
from ..system.onboarding import NodeOnboardingSessionsStore, NodeRegistrationsStore, NodeTrustIssuanceService
from ..system.runtime import StandaloneRuntimeService
from .admin import require_admin_token


class SetAddonEnabledRequest(BaseModel):
    enabled: bool


class NodeOnboardingStartRequest(BaseModel):
    node_name: str
    node_type: str
    node_software_version: str
    protocol_version: str
    hostname: str | None = None
    node_nonce: str


class NodeOnboardingRejectRequest(BaseModel):
    rejection_reason: str | None = None


def _onboarding_error(error: str, message: str, *, retryable: bool = False) -> dict[str, object]:
    return {
        "error": error,
        "message": message,
        "retryable": bool(retryable),
    }


def _onboarding_enabled() -> bool:
    raw = str(os.getenv("SYNTHIA_NODE_ONBOARDING_ENABLED", "")).strip()
    if not raw:
        raw = str(os.getenv("SYNTHIA_AI_NODE_ONBOARDING_ENABLED", "true")).strip()
    return raw.lower() in {"1", "true", "yes", "on"}


def _supported_protocol_versions() -> set[str]:
    raw = str(os.getenv("SYNTHIA_NODE_ONBOARDING_PROTOCOLS", "")).strip()
    if not raw:
        raw = str(os.getenv("SYNTHIA_AI_NODE_ONBOARDING_PROTOCOLS", "1.0")).strip()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _supported_node_types() -> set[str]:
    raw = str(os.getenv("SYNTHIA_NODE_ONBOARDING_SUPPORTED_TYPES", "ai-node")).strip()
    values = {item.strip() for item in raw.split(",") if item.strip()}
    if not values:
        values = {"ai-node"}
    aliases: set[str] = set()
    for value in values:
        canonical = _canonical_node_type(value)
        aliases.add(value)
        aliases.add(canonical)
        if value.endswith("-node"):
            aliases.add(value[: -len("-node")])
        else:
            aliases.add(f"{value}-node")
    return {item for item in aliases if item}


def _canonical_node_type(node_type: str | None) -> str:
    value = str(node_type or "").strip().lower()
    if value.endswith("-node"):
        trimmed = value[: -len("-node")].strip()
        return trimmed or value
    return value


def _build_approval_url(request: Request, session_id: str, state: str) -> str:
    configured = str(os.getenv("SYNTHIA_NODE_ONBOARDING_APPROVAL_URL_BASE", "")).strip()
    if not configured:
        configured = str(os.getenv("SYNTHIA_AI_NODE_ONBOARDING_APPROVAL_URL_BASE", "")).strip()
    if configured.startswith(("http://", "https://")):
        base = configured.rstrip("/")
    else:
        path = configured or "/onboarding/registrations/approve"
        if not path.startswith("/"):
            path = f"/{path}"
        base = f"{str(request.base_url).rstrip('/')}{path}"
    return f"{base}?{urlencode({'sid': session_id, 'state': state})}"


def _admin_actor(x_admin_token: str | None) -> str:
    return "admin_token" if (x_admin_token or "").strip() else "admin_session"


_RATE_WINDOWS: dict[str, list[float]] = {}
_LEGACY_DEPRECATION_DATE = "2026-09-30"


def _rate_limit(key: str, *, limit: int, window_seconds: int) -> bool:
    now = time.time()
    window_start = now - max(window_seconds, 1)
    bucket = _RATE_WINDOWS.setdefault(key, [])
    bucket[:] = [ts for ts in bucket if ts >= window_start]
    if len(bucket) >= max(limit, 1):
        return False
    bucket.append(now)
    return True


def _validate_node_nonce(value: str | None) -> str:
    nonce = str(value or "").strip()
    if len(nonce) < 8 or len(nonce) > 256:
        raise ValueError("node_nonce_invalid")
    return nonce


def _stable_node_id_from_nonce(node_nonce: str) -> str:
    digest = hashlib.sha256(str(node_nonce or "").encode("utf-8")).hexdigest()[:16]
    return f"node-{digest}"


def _enforce_csrf_for_cookie_session(request: Request, x_admin_token: str | None) -> None:
    if (x_admin_token or "").strip():
        return
    trusted_origins: set[str] = {str(request.base_url).rstrip("/")}
    configured_origins = str(os.getenv("SYNTHIA_CSRF_TRUSTED_ORIGINS", "")).strip()
    for item in configured_origins.split(","):
        value = str(item or "").strip().rstrip("/")
        if value.startswith(("http://", "https://")):
            trusted_origins.add(value)
    approval_base = str(os.getenv("SYNTHIA_NODE_ONBOARDING_APPROVAL_URL_BASE", "")).strip()
    if not approval_base:
        approval_base = str(os.getenv("SYNTHIA_AI_NODE_ONBOARDING_APPROVAL_URL_BASE", "")).strip()
    if approval_base.startswith(("http://", "https://")):
        parts = urlsplit(approval_base)
        if parts.scheme and parts.netloc:
            trusted_origins.add(f"{parts.scheme}://{parts.netloc}")

    origin = str(request.headers.get("origin") or "").strip()
    referer = str(request.headers.get("referer") or "").strip()
    if origin and origin.rstrip("/") not in trusted_origins:
        raise HTTPException(status_code=403, detail="csrf_origin_mismatch")
    if not origin and referer and not any(referer.startswith(item) for item in trusted_origins):
        raise HTTPException(status_code=403, detail="csrf_referer_mismatch")


def _record_audit(
    audit_store: AuditLogStore | None,
    *,
    event_type: str,
    actor_role: str,
    actor_id: str,
    details: dict[str, object],
) -> None:
    if audit_store is None:
        return
    try:
        asyncio.run(
            audit_store.record(
                event_type=event_type,
                actor_role=actor_role,
                actor_id=actor_id,
                details=details,
            )
        )
    except Exception:
        return


def _expire_if_needed(store: NodeOnboardingSessionsStore | None) -> None:
    if store is None:
        return
    store.expire_stale_sessions()


def _apply_legacy_deprecation_headers(response: Response) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = _LEGACY_DEPRECATION_DATE
    response.headers["Warning"] = (
        f'299 - "Legacy /api/system/ai-nodes onboarding alias is deprecated; migrate to /api/system/nodes/onboarding/sessions before {_LEGACY_DEPRECATION_DATE}"'
    )


def _session_payload(session) -> dict[str, object]:
    requested_node_type = str((session.request_metadata or {}).get("requested_node_type") or "").strip()
    if not requested_node_type:
        requested_node_type = session.requested_node_type
    return {
        "session_id": session.session_id,
        "session_state": session.session_state,
        "node_name": session.requested_node_name,
        "node_type": session.requested_node_type,
        "node_software_version": session.requested_node_software_version,
        "requested_node_name": session.requested_node_name,
        "requested_node_type": requested_node_type,
        "requested_node_software_version": session.requested_node_software_version,
        "requested_hostname": session.requested_hostname,
        "requested_from_ip": session.requested_from_ip,
        "created_at": session.created_at,
        "expires_at": session.expires_at,
        "approved_at": session.approved_at,
        "rejected_at": session.rejected_at,
        "approved_by_user_id": session.approved_by_user_id,
        "rejection_reason": session.rejection_reason,
        "linked_node_id": session.linked_node_id,
        "final_payload_consumed_at": session.final_payload_consumed_at,
    }


def _registry_state_from_trust_status(value: str | None) -> str:
    status = str(value or "").strip().lower()
    if status in {"trusted", "approved", "pending", "revoked"}:
        return status
    if status == "rejected":
        return "revoked"
    return "pending"


def _node_registry_payload(item) -> dict[str, object]:
    trust_status = str(getattr(item, "trust_status", "") or "").strip().lower()
    return {
        "node_id": getattr(item, "node_id", None),
        "node_name": getattr(item, "node_name", None),
        "node_type": getattr(item, "node_type", None),
        "node_software_version": getattr(item, "node_software_version", None),
        "trust_status": trust_status or "pending",
        "registry_state": _registry_state_from_trust_status(trust_status),
        "approved_by_user_id": getattr(item, "approved_by_user_id", None),
        "approved_at": getattr(item, "approved_at", None),
        "source_onboarding_session_id": getattr(item, "source_onboarding_session_id", None),
        "created_at": getattr(item, "created_at", None),
        "updated_at": getattr(item, "updated_at", None),
    }


def build_system_router(
    registry: AddonRegistry,
    runtime_service: StandaloneRuntimeService | None = None,
    mqtt_approval_service=None,
    onboarding_sessions_store: NodeOnboardingSessionsStore | None = None,
    node_registrations_store: NodeRegistrationsStore | None = None,
    node_trust_issuance: NodeTrustIssuanceService | None = None,
    audit_store: AuditLogStore | None = None,
) -> APIRouter:
    router = APIRouter()
    runtime = runtime_service or StandaloneRuntimeService()

    @router.get("/addons")
    def get_addons():
        return list_addons(registry)

    @router.post("/addons/{addon_id}/enable")
    async def set_addon_enabled(addon_id: str, body: SetAddonEnabledRequest):
        if not registry.has_addon(addon_id):
            raise HTTPException(status_code=404, detail="addon_not_found")
        if registry.is_platform_managed(addon_id) and not body.enabled:
            raise HTTPException(status_code=403, detail="platform_managed_addon_cannot_be_disabled")
        registry.set_enabled(addon_id, body.enabled)
        if mqtt_approval_service is not None:
            if body.enabled:
                await mqtt_approval_service.reconcile(addon_id)
            else:
                await mqtt_approval_service.revoke_or_mark(addon_id, reason="addon_disabled")
        return {"ok": True, "id": addon_id, "enabled": registry.is_enabled(addon_id)}

    @router.get("/addons/errors")
    def get_addon_errors():
        # Helpful when something fails to import but you still want the server up.
        return registry.errors

    @router.post("/system/nodes/onboarding/sessions")
    def start_node_onboarding_session(body: NodeOnboardingStartRequest, request: Request):
        _expire_if_needed(onboarding_sessions_store)
        if onboarding_sessions_store is None or not _onboarding_enabled():
            raise HTTPException(
                status_code=503,
                detail=_onboarding_error("registration_disabled", "node onboarding registration is disabled"),
            )
        source_ip = str(request.client.host if request.client else "unknown")
        if not _rate_limit(f"onboarding:create:{source_ip}", limit=20, window_seconds=60):
            raise HTTPException(status_code=429, detail="rate_limited")
        node_type = str(body.node_type or "").strip()
        if node_type not in _supported_node_types():
            raise HTTPException(
                status_code=400,
                detail=_onboarding_error(
                    "node_type_unsupported",
                    f"unsupported node_type; allowed={','.join(sorted(_supported_node_types()))}",
                ),
            )
        canonical_node_type = _canonical_node_type(node_type)
        protocol_version = str(body.protocol_version or "").strip()
        if protocol_version not in _supported_protocol_versions():
            raise HTTPException(
                status_code=400,
                detail=_onboarding_error("protocol_version_unsupported", "unsupported onboarding protocol version"),
            )
        try:
            node_nonce = _validate_node_nonce(body.node_nonce)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        active = onboarding_sessions_store.find_active_by_node_nonce(node_nonce)
        if active is not None:
            raise HTTPException(
                status_code=409,
                detail=_onboarding_error("duplicate_active_session", "active onboarding session already exists"),
            )

        approval_state = secrets.token_urlsafe(18)
        session = onboarding_sessions_store.start_session(
            node_nonce=node_nonce,
            requested_node_name=body.node_name,
            requested_node_type=canonical_node_type,
            requested_node_software_version=body.node_software_version,
            requested_hostname=body.hostname,
            requested_from_ip=(source_ip if source_ip != "unknown" else None),
            request_metadata={
                "protocol_version": protocol_version,
                "approval_state": approval_state,
                "requested_node_type": node_type,
            },
        )
        _record_audit(
            audit_store,
            event_type="node_onboarding_session_created",
            actor_role="node",
            actor_id=str(session.requested_node_name or "unknown"),
            details={"session_id": session.session_id, "source_ip": source_ip},
        )
        return {
            "ok": True,
            "session": {
                "session_id": session.session_id,
                "onboarding_status": "pending_approval",
                "node_name": session.requested_node_name,
                "node_type": session.requested_node_type,
                "node_software_version": session.requested_node_software_version,
                "requested_node_name": session.requested_node_name,
                "requested_node_type": str((session.request_metadata or {}).get("requested_node_type") or session.requested_node_type),
                "requested_node_software_version": session.requested_node_software_version,
                "approval_url": _build_approval_url(request, session.session_id, approval_state),
                "expires_at": session.expires_at,
                "finalize": {
                    "method": "GET",
                    "path": f"/api/system/nodes/onboarding/sessions/{session.session_id}/finalize",
                },
            },
        }

    @router.get("/system/nodes/onboarding/sessions/{session_id}")
    def get_node_onboarding_session(
        session_id: str,
        request: Request,
        state: str = Query(...),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        _expire_if_needed(onboarding_sessions_store)
        if onboarding_sessions_store is None:
            raise HTTPException(status_code=503, detail="onboarding_sessions_unavailable")
        try:
            session = onboarding_sessions_store.get(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="session_not_found")
        expected = str((session.request_metadata or {}).get("approval_state") or "").strip()
        if not expected or state.strip() != expected:
            raise HTTPException(status_code=400, detail="approval_state_mismatch")
        return {"ok": True, "session": _session_payload(session)}

    @router.get("/system/nodes/onboarding/sessions")
    def list_node_onboarding_sessions(
        request: Request,
        state: str | None = Query(default=None),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        _expire_if_needed(onboarding_sessions_store)
        if onboarding_sessions_store is None:
            raise HTTPException(status_code=503, detail="onboarding_sessions_unavailable")
        items = onboarding_sessions_store.list_sessions(state=state if state else None)
        payload = []
        for session in items:
            payload.append(_session_payload(session))
        return {"ok": True, "items": payload}

    @router.get("/system/nodes/registrations")
    def list_node_registrations(
        request: Request,
        node_type: str | None = Query(default=None),
        trust_status: str | None = Query(default=None),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        entries = node_registrations_store.list()
        if node_type:
            node_type_filter = _canonical_node_type(node_type)
            entries = [item for item in entries if _canonical_node_type(item.node_type) == node_type_filter]
        if trust_status:
            trust_status_filter = str(trust_status).strip().lower()
            entries = [item for item in entries if str(item.trust_status).strip().lower() == trust_status_filter]
        return {"ok": True, "items": [item.to_api_dict() for item in entries]}

    @router.get("/system/nodes/registrations/{node_id}")
    def get_node_registration(
        node_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        item = node_registrations_store.get(node_id)
        if item is None:
            raise HTTPException(status_code=404, detail="node_registration_not_found")
        return {"ok": True, "registration": item.to_api_dict()}

    @router.get("/system/nodes/registry")
    def list_node_registry(
        request: Request,
        state: str | None = Query(default=None),
        node_type: str | None = Query(default=None),
        trust_status: str | None = Query(default=None),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        entries = node_registrations_store.list()
        if node_type:
            node_type_filter = _canonical_node_type(node_type)
            entries = [item for item in entries if _canonical_node_type(item.node_type) == node_type_filter]
        if trust_status:
            trust_status_filter = str(trust_status).strip().lower()
            entries = [item for item in entries if str(item.trust_status).strip().lower() == trust_status_filter]
        payload = [_node_registry_payload(item) for item in entries]
        if state:
            state_filter = str(state).strip().lower()
            payload = [item for item in payload if str(item.get("registry_state") or "").strip().lower() == state_filter]
        return {"ok": True, "items": payload}

    @router.delete("/system/nodes/registrations/{node_id}")
    def delete_node_registration(
        node_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        existing = node_registrations_store.get(node_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="node_registration_not_found")
        removed = node_registrations_store.delete(node_id)
        trust_removed = False
        if node_trust_issuance is not None:
            try:
                trust_removed = bool(node_trust_issuance.revoke_node(node_id))
            except Exception:
                trust_removed = False
        _record_audit(
            audit_store,
            event_type="node_registration_deleted",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"node_id": str(node_id or ""), "removed_trust_record": trust_removed},
        )
        return {
            "ok": True,
            "removed_node_id": str(node_id or ""),
            "removed_registration": bool(removed is not None),
            "removed_trust_record": trust_removed,
        }

    @router.post("/system/nodes/onboarding/sessions/{session_id}/approve")
    def approve_node_onboarding_session(
        session_id: str,
        request: Request,
        state: str = Query(...),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        _enforce_csrf_for_cookie_session(request, x_admin_token)
        _expire_if_needed(onboarding_sessions_store)
        if onboarding_sessions_store is None:
            raise HTTPException(status_code=503, detail="onboarding_sessions_unavailable")
        try:
            session = onboarding_sessions_store.get(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="session_not_found")
        expected = str((session.request_metadata or {}).get("approval_state") or "").strip()
        if not expected or state.strip() != expected:
            raise HTTPException(status_code=400, detail="approval_state_mismatch")
        if str(session.session_state) == "expired":
            raise HTTPException(status_code=409, detail="session_expired")
        linked_node_id = str(session.linked_node_id or "").strip() or _stable_node_id_from_nonce(session.node_nonce)
        try:
            decided = onboarding_sessions_store.approve_session(
                session_id,
                approved_by_user_id=_admin_actor(x_admin_token),
                linked_node_id=linked_node_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        registration_payload = None
        if node_registrations_store is not None:
            try:
                registration = node_registrations_store.upsert_from_approved_session(decided)
                registration_payload = registration.to_api_dict()
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
        _record_audit(
            audit_store,
            event_type="node_onboarding_session_approved",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"session_id": decided.session_id, "linked_node_id": str(decided.linked_node_id or "")},
        )
        response = {"ok": True, "session": decided.to_dict()}
        if registration_payload is not None:
            response["registration"] = registration_payload
        return response

    @router.post("/system/nodes/onboarding/sessions/{session_id}/reject")
    def reject_node_onboarding_session(
        session_id: str,
        body: NodeOnboardingRejectRequest,
        request: Request,
        state: str = Query(...),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        _enforce_csrf_for_cookie_session(request, x_admin_token)
        _expire_if_needed(onboarding_sessions_store)
        if onboarding_sessions_store is None:
            raise HTTPException(status_code=503, detail="onboarding_sessions_unavailable")
        try:
            session = onboarding_sessions_store.get(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="session_not_found")
        expected = str((session.request_metadata or {}).get("approval_state") or "").strip()
        if not expected or state.strip() != expected:
            raise HTTPException(status_code=400, detail="approval_state_mismatch")
        if str(session.session_state) == "expired":
            raise HTTPException(status_code=409, detail="session_expired")
        try:
            decided = onboarding_sessions_store.reject_session(
                session_id,
                rejected_by_user_id=_admin_actor(x_admin_token),
                rejection_reason=body.rejection_reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        _record_audit(
            audit_store,
            event_type="node_onboarding_session_rejected",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"session_id": decided.session_id, "rejection_reason": str(decided.rejection_reason or "")},
        )
        return {"ok": True, "session": decided.to_dict()}

    @router.get("/system/nodes/onboarding/sessions/{session_id}/finalize")
    def finalize_node_onboarding_session(
        session_id: str,
        node_nonce: str = Query(...),
    ):
        _expire_if_needed(onboarding_sessions_store)
        if onboarding_sessions_store is None:
            raise HTTPException(status_code=503, detail="onboarding_sessions_unavailable")
        try:
            nonce = _validate_node_nonce(node_nonce)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not _rate_limit(f"onboarding:finalize:{session_id}:{nonce}", limit=60, window_seconds=60):
            raise HTTPException(status_code=429, detail="rate_limited")
        try:
            session = onboarding_sessions_store.get(session_id)
        except KeyError:
            _record_audit(
                audit_store,
                event_type="node_onboarding_finalize_invalid",
                actor_role="node",
                actor_id="unknown",
                details={"session_id": session_id, "reason": "session_not_found"},
            )
            return {"ok": True, "onboarding_status": "invalid"}

        if str(session.node_nonce).strip() != nonce:
            _record_audit(
                audit_store,
                event_type="node_onboarding_finalize_invalid",
                actor_role="node",
                actor_id=str(session.requested_node_name or "unknown"),
                details={"session_id": session_id, "reason": "node_nonce_mismatch"},
            )
            return {"ok": True, "onboarding_status": "invalid"}

        state = str(session.session_state or "invalid").strip().lower()
        if state == "pending":
            return {"ok": True, "onboarding_status": "pending"}
        if state == "rejected":
            return {
                "ok": True,
                "onboarding_status": "rejected",
                "rejection_reason": session.rejection_reason,
            }
        if state == "expired":
            return {"ok": True, "onboarding_status": "expired"}
        if state == "cancelled":
            return {"ok": True, "onboarding_status": "invalid"}
        if state == "consumed":
            _record_audit(
                audit_store,
                event_type="node_onboarding_finalize_replay",
                actor_role="node",
                actor_id=str(session.requested_node_name or "unknown"),
                details={"session_id": session_id},
            )
            return {"ok": True, "onboarding_status": "consumed", "error": "already_consumed"}
        if state == "approved":
            if node_trust_issuance is None:
                raise HTTPException(status_code=503, detail="trust_issuance_unavailable")
            issued = node_trust_issuance.issue_for_approved_session(session)
            _record_audit(
                audit_store,
                event_type="node_onboarding_trust_issued",
                actor_role="system",
                actor_id="core",
                details={
                    "session_id": session_id,
                    "node_id": str((issued.get("activation") or {}).get("node_id") or ""),
                },
            )
            onboarding_sessions_store.consume_final_payload(session_id, actor_id="node_finalize")
            if node_registrations_store is not None:
                try:
                    node_registrations_store.mark_trusted_by_session(session_id)
                except Exception:
                    pass
            _record_audit(
                audit_store,
                event_type="node_onboarding_trust_consumed",
                actor_role="node",
                actor_id=str(session.requested_node_name or "unknown"),
                details={"session_id": session_id},
            )
            return {
                "ok": True,
                "onboarding_status": "approved",
                "activation": issued.get("activation"),
            }
        return {"ok": True, "onboarding_status": "invalid"}

    @router.post("/system/ai-nodes/onboarding/sessions", include_in_schema=False)
    def legacy_start_ai_node_onboarding_session(body: NodeOnboardingStartRequest, request: Request, response: Response):
        _apply_legacy_deprecation_headers(response)
        return start_node_onboarding_session(body, request)

    @router.get("/system/ai-nodes/onboarding/sessions", include_in_schema=False)
    def legacy_list_ai_node_onboarding_sessions(
        request: Request,
        response: Response,
        state: str | None = Query(default=None),
        x_admin_token: str | None = Header(default=None),
    ):
        _apply_legacy_deprecation_headers(response)
        return list_node_onboarding_sessions(request, state=state, x_admin_token=x_admin_token)

    @router.get("/system/ai-nodes/onboarding/sessions/{session_id}", include_in_schema=False)
    def legacy_get_ai_node_onboarding_session(
        session_id: str,
        request: Request,
        response: Response,
        state: str = Query(...),
        x_admin_token: str | None = Header(default=None),
    ):
        _apply_legacy_deprecation_headers(response)
        return get_node_onboarding_session(session_id, request, state=state, x_admin_token=x_admin_token)

    @router.post("/system/ai-nodes/onboarding/sessions/{session_id}/approve", include_in_schema=False)
    def legacy_approve_ai_node_onboarding_session(
        session_id: str,
        request: Request,
        response: Response,
        state: str = Query(...),
        x_admin_token: str | None = Header(default=None),
    ):
        _apply_legacy_deprecation_headers(response)
        return approve_node_onboarding_session(session_id, request, state=state, x_admin_token=x_admin_token)

    @router.post("/system/ai-nodes/onboarding/sessions/{session_id}/reject", include_in_schema=False)
    def legacy_reject_ai_node_onboarding_session(
        session_id: str,
        body: NodeOnboardingRejectRequest,
        request: Request,
        response: Response,
        state: str = Query(...),
        x_admin_token: str | None = Header(default=None),
    ):
        _apply_legacy_deprecation_headers(response)
        return reject_node_onboarding_session(session_id, body, request, state=state, x_admin_token=x_admin_token)

    @router.get("/system/ai-nodes/onboarding/sessions/{session_id}/finalize", include_in_schema=False)
    def legacy_finalize_ai_node_onboarding_session(
        session_id: str,
        response: Response,
        node_nonce: str = Query(...),
    ):
        _apply_legacy_deprecation_headers(response)
        return finalize_node_onboarding_session(session_id, node_nonce=node_nonce)

    @router.get("/system/addons/runtime")
    def list_standalone_runtimes(
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        items = [item.model_dump(mode="json") for item in runtime.list_standalone_addon_runtimes()]
        return {"ok": True, "items": items}

    @router.get("/system/addons/runtime/{addon_id}")
    def get_standalone_runtime(
        addon_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        item = runtime.get_standalone_addon_runtime(addon_id)
        return {"ok": True, "runtime": item.model_dump(mode="json")}

    return router

from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel

from ..addons.registry import AddonRegistry, list_addons
from ..system.onboarding import NodeOnboardingSessionsStore, NodeTrustIssuanceService
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
    return str(os.getenv("SYNTHIA_AI_NODE_ONBOARDING_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}


def _supported_protocol_versions() -> set[str]:
    raw = str(os.getenv("SYNTHIA_AI_NODE_ONBOARDING_PROTOCOLS", "1.0")).strip()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _build_approval_url(request: Request, session_id: str, state: str) -> str:
    configured = str(os.getenv("SYNTHIA_AI_NODE_ONBOARDING_APPROVAL_URL_BASE", "")).strip()
    if configured.startswith(("http://", "https://")):
        base = configured.rstrip("/")
    else:
        path = configured or "/onboarding/nodes/approve"
        if not path.startswith("/"):
            path = f"/{path}"
        base = f"{str(request.base_url).rstrip('/')}{path}"
    return f"{base}?{urlencode({'sid': session_id, 'state': state})}"


def _admin_actor(x_admin_token: str | None) -> str:
    return "admin_token" if (x_admin_token or "").strip() else "admin_session"


def build_system_router(
    registry: AddonRegistry,
    runtime_service: StandaloneRuntimeService | None = None,
    mqtt_approval_service=None,
    onboarding_sessions_store: NodeOnboardingSessionsStore | None = None,
    node_trust_issuance: NodeTrustIssuanceService | None = None,
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
        if onboarding_sessions_store is None or not _onboarding_enabled():
            raise HTTPException(
                status_code=503,
                detail=_onboarding_error("registration_disabled", "node onboarding registration is disabled"),
            )
        node_type = str(body.node_type or "").strip()
        if node_type != "ai-node":
            raise HTTPException(
                status_code=400,
                detail=_onboarding_error("node_type_unsupported", "only node_type=ai-node is supported"),
            )
        protocol_version = str(body.protocol_version or "").strip()
        if protocol_version not in _supported_protocol_versions():
            raise HTTPException(
                status_code=400,
                detail=_onboarding_error("protocol_version_unsupported", "unsupported onboarding protocol version"),
            )

        active = onboarding_sessions_store.find_active_by_node_nonce(body.node_nonce)
        if active is not None:
            raise HTTPException(
                status_code=409,
                detail=_onboarding_error("duplicate_active_session", "active onboarding session already exists"),
            )

        approval_state = secrets.token_urlsafe(18)
        session = onboarding_sessions_store.start_session(
            node_nonce=body.node_nonce,
            requested_node_name=body.node_name,
            requested_node_type=node_type,
            requested_node_software_version=body.node_software_version,
            requested_hostname=body.hostname,
            requested_from_ip=(request.client.host if request.client else None),
            request_metadata={
                "protocol_version": protocol_version,
                "approval_state": approval_state,
            },
        )
        return {
            "ok": True,
            "session": {
                "session_id": session.session_id,
                "onboarding_status": "pending_approval",
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
        state: str | None = Query(default=None),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if onboarding_sessions_store is None:
            raise HTTPException(status_code=503, detail="onboarding_sessions_unavailable")
        try:
            session = onboarding_sessions_store.get(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="session_not_found")
        if state is not None:
            expected = str((session.request_metadata or {}).get("approval_state") or "").strip()
            if not expected or state.strip() != expected:
                raise HTTPException(status_code=400, detail="approval_state_mismatch")
        return {
            "ok": True,
            "session": {
                "session_id": session.session_id,
                "session_state": session.session_state,
                "requested_node_name": session.requested_node_name,
                "requested_node_type": session.requested_node_type,
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
            },
        }

    @router.post("/system/nodes/onboarding/sessions/{session_id}/approve")
    def approve_node_onboarding_session(
        session_id: str,
        request: Request,
        state: str | None = Query(default=None),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if onboarding_sessions_store is None:
            raise HTTPException(status_code=503, detail="onboarding_sessions_unavailable")
        try:
            session = onboarding_sessions_store.get(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="session_not_found")
        if state is not None:
            expected = str((session.request_metadata or {}).get("approval_state") or "").strip()
            if not expected or state.strip() != expected:
                raise HTTPException(status_code=400, detail="approval_state_mismatch")
        linked_node_id = str(session.linked_node_id or "").strip() or f"node-{session.session_id[:12]}"
        try:
            decided = onboarding_sessions_store.approve_session(
                session_id,
                approved_by_user_id=_admin_actor(x_admin_token),
                linked_node_id=linked_node_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"ok": True, "session": decided.to_dict()}

    @router.post("/system/nodes/onboarding/sessions/{session_id}/reject")
    def reject_node_onboarding_session(
        session_id: str,
        body: NodeOnboardingRejectRequest,
        request: Request,
        state: str | None = Query(default=None),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if onboarding_sessions_store is None:
            raise HTTPException(status_code=503, detail="onboarding_sessions_unavailable")
        try:
            session = onboarding_sessions_store.get(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="session_not_found")
        if state is not None:
            expected = str((session.request_metadata or {}).get("approval_state") or "").strip()
            if not expected or state.strip() != expected:
                raise HTTPException(status_code=400, detail="approval_state_mismatch")
        try:
            decided = onboarding_sessions_store.reject_session(
                session_id,
                rejected_by_user_id=_admin_actor(x_admin_token),
                rejection_reason=body.rejection_reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"ok": True, "session": decided.to_dict()}

    @router.get("/system/nodes/onboarding/sessions/{session_id}/finalize")
    def finalize_node_onboarding_session(
        session_id: str,
        node_nonce: str = Query(...),
    ):
        if onboarding_sessions_store is None:
            raise HTTPException(status_code=503, detail="onboarding_sessions_unavailable")
        nonce = str(node_nonce or "").strip()
        if not nonce:
            raise HTTPException(status_code=400, detail="node_nonce_required")
        try:
            session = onboarding_sessions_store.get(session_id)
        except KeyError:
            return {"ok": True, "onboarding_status": "invalid"}

        if str(session.node_nonce).strip() != nonce:
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
            return {"ok": True, "onboarding_status": "approved", "already_consumed": True}
        if state == "approved":
            if node_trust_issuance is None:
                raise HTTPException(status_code=503, detail="trust_issuance_unavailable")
            issued = node_trust_issuance.issue_for_approved_session(session)
            return {
                "ok": True,
                "onboarding_status": "approved",
                "activation": issued.get("activation"),
            }
        return {"ok": True, "onboarding_status": "invalid"}

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

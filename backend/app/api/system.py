from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel

from ..nodes import NodeServiceAuthorizeRequest, TaskExecutionResolutionRequest
from ..addons.registry import AddonRegistry, list_addons
from ..system.audit import AuditLogStore
from ..system.auth.tokens import sign_hs256
from ..system.onboarding import (
    ALLOWED_NODE_TELEMETRY_EVENTS,
    CapabilityManifestValidationError,
    NodeCapabilityAcceptanceService,
    NodeGovernanceService,
    NodeGovernanceStatusService,
    ModelRoutingRegistryService,
    NodeOnboardingSessionsStore,
    NodeRegistrationsStore,
    NodeBudgetService,
    NodeTelemetryService,
    NodeTrustIssuanceService,
    capability_taxonomy_payload,
    node_registry_payload,
    normalize_provider_capability_report,
    validate_capability_declaration,
)
from ..system.onboarding.provider_capability_normalization import normalize_capacity_descriptor
from ..system.runtime import StandaloneRuntimeService
from ..system.services import NodeServiceResolutionService, ServiceCatalogStore
from .admin import require_admin_token


class SetAddonEnabledRequest(BaseModel):
    enabled: bool


class NodeOnboardingStartRequest(BaseModel):
    node_name: str
    node_type: str
    node_software_version: str
    protocol_version: str
    hostname: str | None = None
    ui_endpoint: str | None = None
    node_nonce: str
    node_id: str | None = None


class NodeOnboardingRejectRequest(BaseModel):
    rejection_reason: str | None = None


class NodeCapabilityDeclarationRequest(BaseModel):
    manifest: dict


class NodeGovernanceRefreshRequest(BaseModel):
    node_id: str
    current_governance_version: str | None = None


class NodeTelemetryIngestRequest(BaseModel):
    node_id: str
    event_type: str
    event_state: str | None = None
    message: str | None = None
    payload: dict | None = None


class ProviderModelPolicyUpdateRequest(BaseModel):
    allowed_models: list[str]


class ProviderCapabilityReportRequest(BaseModel):
    node_id: str
    provider_intelligence: list[dict]
    service_capacity: dict | None = None
    node_available: bool = True
    observed_at: str | None = None


class NodeBudgetDeclarationRequest(BaseModel):
    node_id: str
    currency: str = "USD"
    compute_unit: str = "cost_units"
    default_period: str = "monthly"
    supports_money_budget: bool = True
    supports_compute_budget: bool = True
    supports_customer_allocations: bool = True
    supports_provider_allocations: bool = False
    supported_providers: list[str] = []
    setup_requirements: list[str] = []
    suggested_money_limit: float | None = None
    suggested_compute_limit: float | None = None


class BudgetAllocationUpsertRequest(BaseModel):
    subject_id: str
    money_limit: float | None = None
    compute_limit: float | None = None


class NodeBudgetConfigUpsertRequest(BaseModel):
    currency: str = "USD"
    compute_unit: str = "cost_units"
    period: str = "monthly"
    reset_policy: str = "calendar"
    enforcement_mode: str = "hard_stop"
    overcommit_enabled: bool = False
    shared_customer_pool: bool = False
    shared_provider_pool: bool = False
    node_money_limit: float | None = None
    node_compute_limit: float | None = None


class NodeBudgetBundleUpsertRequest(BaseModel):
    node_budget: NodeBudgetConfigUpsertRequest
    customer_allocations: list[BudgetAllocationUpsertRequest] = []
    provider_allocations: list[BudgetAllocationUpsertRequest] = []


class NodeBudgetUsageReportRequest(BaseModel):
    node_id: str
    job_id: str
    status: str
    actual_money_spend: float | None = None
    actual_compute_spend: float | None = None


class NodeBudgetPolicyRefreshRequest(BaseModel):
    node_id: str
    current_budget_policy_version: str | None = None
    current_governance_version: str | None = None


class NodeBudgetUsageSummaryRequest(BaseModel):
    node_id: str
    service: str = "ai.inference"
    grant_id: str
    provider: str | None = None
    model_id: str | None = None
    task_family: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    used_requests: int = 0
    used_tokens: int = 0
    used_cost_cents: int = 0
    denials: int = 0
    error_counts: dict | None = None
    metadata: dict | None = None


class NodeBudgetTopUpRequest(BaseModel):
    money_delta: float | None = None
    compute_delta: float | None = None


class NodeBudgetOverrideRequest(BaseModel):
    enforcement_mode: str | None = None
    overcommit_enabled: bool | None = None


class NodeBudgetForceReleaseRequest(BaseModel):
    job_id: str | None = None
    reservation_id: str | None = None
    reason: str | None = None


NODE_BOOTSTRAP_TOPIC = "hexe/bootstrap/core"


def _onboarding_error(error: str, message: str, *, retryable: bool = False) -> dict[str, object]:
    return {
        "error": error,
        "message": message,
        "retryable": bool(retryable),
    }


def _node_trust_status_payload(
    *,
    node_id: str,
    trust_record,
    registration,
) -> dict[str, object]:
    trust_status = str(getattr(trust_record, "trust_status", "") or "").strip().lower() or "unknown"
    revocation_action = str(getattr(trust_record, "revocation_action", "") or "").strip() or None
    revocation_reason = str(getattr(trust_record, "revocation_reason", "") or "").strip() or None
    revoked_at = str(getattr(trust_record, "revoked_at", "") or "").strip() or None
    registry_present = registration is not None
    registry_state = None
    if registration is not None:
        registry_state = str(getattr(registration, "trust_status", "") or "").strip().lower() or None
    support_state = "supported"
    message = "Node trust is active."
    if trust_status == "revoked":
        support_state = "removed" if revocation_action == "remove" else "revoked"
        if revocation_action == "remove":
            message = "This node was removed by Core and is no longer trusted."
        else:
            message = "This node trust was revoked by Core and is no longer trusted."
    return {
        "ok": True,
        "node_id": node_id,
        "trust_status": trust_status,
        "supported": bool(trust_status == "trusted"),
        "support_state": support_state,
        "registry_present": registry_present,
        "registry_state": registry_state,
        "revoked_at": revoked_at,
        "revocation_reason": revocation_reason,
        "revocation_action": revocation_action,
        "message": message,
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


def _node_status_stale_after_s() -> int:
    raw = str(os.getenv("SYNTHIA_NODE_STATUS_STALE_AFTER_S", "300")).strip()
    try:
        return max(30, int(raw))
    except Exception:
        return 300


def _node_status_inactive_after_s() -> int:
    raw = str(os.getenv("SYNTHIA_NODE_STATUS_INACTIVE_AFTER_S", "1800")).strip()
    try:
        inactive_after = max(60, int(raw))
    except Exception:
        inactive_after = 1800
    return max(inactive_after, _node_status_stale_after_s() + 1)


def _supported_node_types() -> set[str]:
    raw = str(os.getenv("SYNTHIA_NODE_ONBOARDING_SUPPORTED_TYPES", "ai-node,email-node")).strip()
    values = {item.strip() for item in raw.split(",") if item.strip()}
    if not values:
        values = {"ai-node", "email-node"}
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


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _node_topic_scope(node_id: str) -> str:
    node_key = str(node_id or "").strip()
    return f"hexe/nodes/{node_key}/#"


def _profile_for_registration(node_capability_acceptance, registration):
    if node_capability_acceptance is None or registration is None:
        return None
    profile_id = str(getattr(registration, "capability_profile_id", "") or "").strip()
    if not profile_id:
        return None
    return node_capability_acceptance.get_profile(profile_id)


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


def _validate_node_id(value: str | None) -> str:
    node_id = str(value or "").strip()
    if len(node_id) < 8 or len(node_id) > 128:
        raise ValueError("node_id_invalid")
    try:
        parsed = uuid.UUID(node_id)
    except ValueError:
        parsed = None
    if parsed is not None and parsed.version == 4 and str(parsed) == node_id.lower():
        return node_id
    if node_id.startswith("node-"):
        tail = node_id[len("node-") :]
        if not tail:
            raise ValueError("node_id_invalid")
        if not all(ch.isalnum() or ch in {"_", "-"} for ch in tail):
            raise ValueError("node_id_invalid")
        return node_id
    raise ValueError("node_id_invalid")


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
        audit_store.record_sync(
            event_type=event_type,
            actor_role=actor_role,
            actor_id=actor_id,
            details=details,
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
        "requested_ui_endpoint": session.requested_ui_endpoint,
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


def build_system_router(
    registry: AddonRegistry,
    runtime_service: StandaloneRuntimeService | None = None,
    mqtt_manager=None,
    service_token_key_store=None,
    service_catalog_store: ServiceCatalogStore | None = None,
    mqtt_approval_service=None,
    mqtt_integration_state_store=None,
    mqtt_credential_store=None,
    mqtt_runtime_reconciler=None,
    onboarding_sessions_store: NodeOnboardingSessionsStore | None = None,
    node_registrations_store: NodeRegistrationsStore | None = None,
    node_trust_issuance: NodeTrustIssuanceService | None = None,
    node_capability_acceptance: NodeCapabilityAcceptanceService | None = None,
    node_governance_service: NodeGovernanceService | None = None,
    node_governance_status_service: NodeGovernanceStatusService | None = None,
    node_telemetry_service: NodeTelemetryService | None = None,
    node_budget_service: NodeBudgetService | None = None,
    provider_model_policy_service=None,
    model_routing_registry_service: ModelRoutingRegistryService | None = None,
    audit_store: AuditLogStore | None = None,
) -> APIRouter:
    router = APIRouter()
    runtime = runtime_service or StandaloneRuntimeService()
    node_service_resolution = NodeServiceResolutionService(service_catalog_store) if service_catalog_store is not None else None

    async def _reconcile_mqtt_authority(reason: str) -> None:
        if mqtt_runtime_reconciler is None:
            return
        reconcile_fn = getattr(mqtt_runtime_reconciler, "reconcile_authority", None)
        if callable(reconcile_fn):
            await reconcile_fn(reason=reason)

    async def _provision_node_mqtt_principal(activation: dict[str, object] | None) -> None:
        if not isinstance(activation, dict):
            return
        if mqtt_integration_state_store is None or mqtt_credential_store is None:
            return
        node_id = str(activation.get("node_id") or "").strip()
        identity = str(activation.get("operational_mqtt_identity") or "").strip()
        token = str(activation.get("operational_mqtt_token") or "").strip()
        if not node_id or not identity or not token:
            raise HTTPException(status_code=503, detail="mqtt_node_provisioning_missing_activation_fields")
        principal_id = f"node:{node_id}"
        topic_scope = _node_topic_scope(node_id)
        from ..system.mqtt.integration_models import MqttPrincipal

        state = await mqtt_integration_state_store.get_state()
        current = state.principals.get(principal_id)
        principal = current.model_copy(deep=True) if current is not None else MqttPrincipal(
            principal_id=principal_id,
            principal_type="synthia_node",
            status="active",
            logical_identity=node_id,
            linked_node_id=node_id,
        )
        principal.principal_type = "synthia_node"
        principal.status = "active"
        principal.logical_identity = node_id
        principal.linked_node_id = node_id
        principal.username = identity
        principal.managed_by = "node_onboarding"
        principal.publish_topics = [topic_scope]
        principal.subscribe_topics = [NODE_BOOTSTRAP_TOPIC, topic_scope]
        principal.notes = "managed by node onboarding trust activation"
        principal.last_activated_at = _utcnow_iso()
        principal.last_revoked_at = None
        await mqtt_integration_state_store.upsert_principal(principal)
        configured = mqtt_credential_store.set_principal_password(
            principal_id=principal_id,
            principal_type="synthia_node",
            username=identity,
            password=token,
        )
        if not configured:
            raise HTTPException(status_code=503, detail="mqtt_node_credential_write_failed")
        await _reconcile_mqtt_authority(reason=f"node_finalize:{node_id}")

    def _ensure_node_governance_bundle(node_id: str):
        if (
            node_governance_service is None
            or node_registrations_store is None
            or node_capability_acceptance is None
        ):
            return None
        registration = node_registrations_store.get(node_id)
        profile = _profile_for_registration(node_capability_acceptance, registration)
        if registration is None or profile is None:
            return None
        bundle = node_governance_service.ensure_current_for_node(
            node_id=node_id,
            node_type=str(getattr(registration, "node_type", "") or ""),
            profile=profile,
        )
        if node_governance_status_service is not None:
            node_governance_status_service.mark_issued(
                node_id=node_id,
                governance_version=bundle.governance_version,
                issued_timestamp=bundle.issued_timestamp,
            )
        return bundle

    async def _issue_service_token_for_node(*, node_id: str, audience: str, scopes: list[str]) -> tuple[str, dict[str, object]]:
        if service_token_key_store is None:
            raise HTTPException(status_code=503, detail="service_token_key_store_unavailable")
        key = await service_token_key_store.active_key()
        now = int(time.time())
        ttl_s = 600
        try:
            ttl_s = max(60, int(str(os.getenv("SYNTHIA_NODE_SERVICE_TOKEN_TTL_S", "600")).strip()))
        except Exception:
            ttl_s = 600
        payload = {
            "sub": node_id,
            "aud": audience,
            "scp": [str(scope).strip() for scope in scopes if str(scope).strip()],
            "exp": now + ttl_s,
            "jti": f"node-{node_id}-{secrets.token_urlsafe(12)}",
            "iat": now,
        }
        header = {"alg": "HS256", "typ": "JWT", "kid": str(key["kid"])}
        token = sign_hs256(header, payload, secret=str(key["secret"]))
        return token, payload

    async def _publish_budget_policy_snapshot(node_id: str):
        if mqtt_manager is None or node_budget_service is None:
            return []
        freshness = _observe_governance_freshness(node_id)
        if bool(freshness.get("outdated")):
            return []
        bundle = _ensure_node_governance_bundle(node_id)
        governance_version = str(getattr(bundle, "governance_version", "") or "") or None
        payload = node_budget_service.budget_policy(node_id, governance_version=governance_version)
        publishes = []
        for topic in node_budget_service.budget_grant_topics(node_id):
            publishes.append(await mqtt_manager.publish(topic=topic, payload=payload, retain=True, qos=1))
        return publishes

    async def _publish_budget_revocations(node_id: str, *, reason: str):
        if mqtt_manager is None or node_budget_service is None:
            return []
        publishes = []
        for payload in node_budget_service.budget_revocation_payloads(node_id, reason=reason):
            for topic in node_budget_service.budget_revocation_topics(
                node_id=node_id,
                grant_id=str(payload.get("grant_id") or "").strip() or None,
            ):
                publishes.append(await mqtt_manager.publish(topic=topic, payload=payload, retain=True, qos=1))
        return publishes

    def _observe_governance_freshness(node_id: str) -> dict[str, object]:
        if node_governance_status_service is None:
            return {
                "state": "pending",
                "stale_for_s": None,
                "last_contact_at": None,
                "critical_after_s": 21600,
                "outdated_after_s": 86400,
                "outdated": False,
            }
        freshness = node_governance_status_service.governance_freshness(node_id)
        status = node_governance_status_service.get_status(node_id)
        current_state = str(freshness.get("state") or "pending")
        prior_state = str(getattr(status, "freshness_state", "") or "").strip() or None
        if prior_state != current_state:
            node_governance_status_service.record_freshness_state(node_id=node_id, freshness_state=current_state)
            _record_audit(
                audit_store,
                event_type="node_governance_freshness_changed",
                actor_role="system",
                actor_id="governance_freshness_monitor",
                details={
                    "node_id": node_id,
                    "previous_state": prior_state,
                    "freshness_state": current_state,
                    "stale_for_s": freshness.get("stale_for_s"),
                    "last_contact_at": freshness.get("last_contact_at"),
                },
            )
            freshness = node_governance_status_service.governance_freshness(node_id)
        return freshness

    def _reject_if_outdated_for_new_contracts(node_id: str) -> None:
        freshness = _observe_governance_freshness(node_id)
        if bool(freshness.get("outdated")):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "node_governance_outdated",
                    "message": "node governance refresh is outdated; refresh governance before requesting new contracts",
                    "governance_freshness_state": freshness.get("state"),
                    "governance_stale_for_s": freshness.get("stale_for_s"),
                },
            )

    async def _deprovision_node_mqtt_principal(node_id: str, *, reason: str) -> None:
        node_key = str(node_id or "").strip()
        if not node_key:
            return
        principal_id = f"node:{node_key}"
        if mqtt_integration_state_store is not None:
            await mqtt_integration_state_store.remove_principal(principal_id)
        if mqtt_credential_store is not None:
            rotate = getattr(mqtt_credential_store, "rotate_principal", None)
            if callable(rotate):
                rotate(principal_id)
        await _reconcile_mqtt_authority(reason=reason)

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
        requested_ui_endpoint = str(body.ui_endpoint or "").strip() or None
        if requested_ui_endpoint:
            parsed_ui = urlsplit(requested_ui_endpoint)
            if parsed_ui.scheme not in {"http", "https"} or not parsed_ui.netloc:
                raise HTTPException(
                    status_code=400,
                    detail=_onboarding_error("ui_endpoint_invalid", "ui_endpoint must be an absolute http(s) url"),
                )
        try:
            node_nonce = _validate_node_nonce(body.node_nonce)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        requested_node_id = None
        if str(body.node_id or "").strip():
            try:
                requested_node_id = _validate_node_id(body.node_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

        active = onboarding_sessions_store.find_active_by_node_nonce(node_nonce)
        if active is not None:
            raise HTTPException(
                status_code=409,
                detail=_onboarding_error("duplicate_active_session", "active onboarding session already exists"),
            )
        node_id = requested_node_id or _stable_node_id_from_nonce(node_nonce)
        if node_registrations_store is not None:
            existing_registration = node_registrations_store.get(node_id)
            if existing_registration is not None:
                raise HTTPException(
                    status_code=409,
                    detail=_onboarding_error(
                        "duplicate_node_identity",
                        "node identity already registered",
                    ),
                )

        approval_state = secrets.token_urlsafe(18)
        session = onboarding_sessions_store.start_session(
            node_nonce=node_nonce,
            requested_node_name=body.node_name,
            requested_node_type=canonical_node_type,
            requested_node_software_version=body.node_software_version,
            requested_hostname=body.hostname,
            requested_ui_endpoint=requested_ui_endpoint,
            requested_from_ip=(source_ip if source_ip != "unknown" else None),
            request_metadata={
                "protocol_version": protocol_version,
                "approval_state": approval_state,
                "requested_node_type": node_type,
                "requested_node_id": requested_node_id,
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
                "requested_hostname": session.requested_hostname,
                "requested_ui_endpoint": session.requested_ui_endpoint,
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
        for item in entries:
            _observe_governance_freshness(str(getattr(item, "node_id", "") or ""))
        return {"ok": True, "items": [node_registry_payload(item, node_governance_status_service) for item in entries]}

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
        _observe_governance_freshness(node_id)
        return {"ok": True, "registration": node_registry_payload(item, node_governance_status_service)}

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
        for item in entries:
            _observe_governance_freshness(str(getattr(item, "node_id", "") or ""))
        payload = [node_registry_payload(item, node_governance_status_service) for item in entries]
        if state:
            state_filter = str(state).strip().lower()
            payload = [item for item in payload if str(item.get("registry_state") or "").strip().lower() == state_filter]
        return {"ok": True, "items": payload}

    @router.post("/system/nodes/capabilities/declaration")
    def declare_node_capabilities(
        body: NodeCapabilityDeclarationRequest,
        request: Request,
        x_node_trust_token: str | None = Header(default=None),
    ):
        node_token = str(x_node_trust_token or "").strip()
        if not node_token:
            raise HTTPException(status_code=401, detail="node_trust_token_required")
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")
        if node_capability_acceptance is None:
            raise HTTPException(status_code=503, detail="capability_acceptance_unavailable")

        try:
            manifest = validate_capability_declaration(dict(body.manifest or {}))
        except CapabilityManifestValidationError as exc:
            detail = str(exc)
            if "unsupported_capability_manifest_version" in detail:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "unsupported_capability_version",
                        "message": detail,
                    },
                )
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_schema",
                    "message": detail,
                },
            )

        node_payload = manifest.get("node") if isinstance(manifest.get("node"), dict) else {}
        node_id = str(node_payload.get("node_id") or "").strip()
        if not node_id:
            raise HTTPException(status_code=400, detail={"error": "invalid_schema", "message": "node_id_required"})

        trust_record = node_trust_issuance.authenticate_node(node_id, node_token)
        if trust_record is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})

        registration = node_registrations_store.get(node_id)
        if registration is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not registered"})
        if str(registration.trust_status or "").strip().lower() != "trusted":
            raise HTTPException(
                status_code=403,
                detail={"error": "untrusted_node", "message": f"node trust_status is {registration.trust_status}"},
            )

        registration.declared_capabilities = list(manifest.get("declared_task_families") or [])
        registration.enabled_providers = list(manifest.get("enabled_providers") or [])
        registration.provider_intelligence = [
            dict(item) for item in list(manifest.get("provider_intelligence") or []) if isinstance(item, dict)
        ]
        registration.capability_declaration_version = str(manifest.get("manifest_version") or "").strip() or None
        registration.capability_declaration_timestamp = _utcnow_iso()
        accepted = node_capability_acceptance.evaluate(node_id=node_id, manifest=manifest)
        if not accepted.accepted:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": accepted.error_code or "capability_rejected",
                    "message": accepted.message or "capability declaration rejected",
                },
            )
        profile = accepted.profile
        if profile is not None:
            registration.provider_intelligence = [dict(item) for item in list(profile.provider_intelligence or []) if isinstance(item, dict)]
        registration.capability_profile_id = profile.profile_id if profile is not None else None
        node_registrations_store.upsert(registration)
        if model_routing_registry_service is not None and profile is not None:
            model_routing_registry_service.record_provider_intelligence(
                node_id=node_id,
                provider_intelligence=[dict(item) for item in list(profile.provider_intelligence or []) if isinstance(item, dict)],
                node_available=(str(registration.trust_status or "").strip().lower() == "trusted"),
                source="capability_declaration",
            )
        issued_governance = None
        if node_governance_service is not None and profile is not None:
            issued_governance = node_governance_service.ensure_current_for_node(
                node_id=node_id,
                node_type=registration.node_type,
                profile=profile,
            )
            if node_governance_status_service is not None:
                node_governance_status_service.mark_issued(
                    node_id=node_id,
                    governance_version=issued_governance.governance_version,
                    issued_timestamp=issued_governance.issued_timestamp,
                )

        _record_audit(
            audit_store,
            event_type="node_capability_declaration_accepted",
            actor_role="node",
            actor_id=node_id,
            details={
                "node_id": node_id,
                "manifest_version": registration.capability_declaration_version or "",
                "declared_capability_count": len(registration.declared_capabilities),
                "enabled_provider_count": len(registration.enabled_providers),
                "provider_intelligence_count": len(registration.provider_intelligence),
                "capability_profile_id": registration.capability_profile_id or "",
                "governance_version": str(getattr(issued_governance, "governance_version", "") or ""),
                "source_ip": str(request.client.host if request.client else "unknown"),
            },
        )

        response_payload = {
            "ok": True,
            "acceptance_status": "accepted",
            "node_id": node_id,
            "manifest_version": registration.capability_declaration_version,
            "accepted_at": registration.capability_declaration_timestamp,
            "declared_capabilities": list(registration.declared_capabilities),
            "enabled_providers": list(registration.enabled_providers),
            "provider_intelligence": [dict(item) for item in list(registration.provider_intelligence or []) if isinstance(item, dict)],
            "unified_model_descriptors": (
                [dict(item) for item in list(profile.unified_model_descriptors or []) if isinstance(item, dict)]
                if profile is not None
                else []
            ),
            "capability_profile_id": registration.capability_profile_id,
            "capability_taxonomy": capability_taxonomy_payload(
                declared_task_families=list(registration.declared_capabilities),
                enabled_providers=list(registration.enabled_providers),
                provider_intelligence=[
                    dict(item) for item in list(registration.provider_intelligence or []) if isinstance(item, dict)
                ],
                capability_status="accepted",
                governance_sync_status="issued" if issued_governance is not None else "pending",
                operational_ready=bool(
                    str(registration.trust_status or "").strip().lower() == "trusted" and issued_governance is not None
                ),
            ),
        }
        if issued_governance is not None:
            response_payload["governance_version"] = issued_governance.governance_version
            response_payload["governance_issued_at"] = issued_governance.issued_timestamp
        return response_payload

    @router.post("/system/nodes/budgets/declaration")
    def declare_node_budget_capabilities(
        body: NodeBudgetDeclarationRequest,
        request: Request,
        x_node_trust_token: str | None = Header(default=None),
    ):
        node_token = str(x_node_trust_token or "").strip()
        if not node_token:
            raise HTTPException(status_code=401, detail="node_trust_token_required")
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")

        node_id = str(body.node_id or "").strip()
        trust_record = node_trust_issuance.authenticate_node(node_id, node_token)
        if trust_record is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})
        registration = node_registrations_store.get(node_id)
        if registration is None or str(registration.trust_status or "").strip().lower() != "trusted":
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not registered"})
        try:
            declaration = node_budget_service.declare_budget_capabilities(node_id=node_id, payload=body.model_dump(mode="json"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc), "message": str(exc)})
        _record_audit(
            audit_store,
            event_type="node_budget_capabilities_declared",
            actor_role="node",
            actor_id=node_id,
            details={
                "node_id": node_id,
                "supports_provider_allocations": bool(declaration.get("supports_provider_allocations")),
                "supports_customer_allocations": bool(declaration.get("supports_customer_allocations")),
                "source_ip": str(request.client.host if request.client else "unknown"),
            },
        )
        return {"ok": True, "node_id": node_id, "declaration": declaration}

    @router.get("/system/nodes/budgets")
    def list_node_budgets(
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        return {"ok": True, "items": node_budget_service.list_bundles()}

    @router.get("/system/nodes/budgets/policy/current")
    def get_node_budget_policy_current(
        response: Response,
        node_id: str = Query(...),
        x_node_trust_token: str | None = Header(default=None),
    ):
        node_token = str(x_node_trust_token or "").strip()
        if not node_token:
            raise HTTPException(status_code=401, detail="node_trust_token_required")
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")
        if node_trust_issuance.authenticate_node(node_id, node_token) is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})
        registration = node_registrations_store.get(node_id)
        if registration is None or str(registration.trust_status or "").strip().lower() != "trusted":
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not registered"})
        _reject_if_outdated_for_new_contracts(node_id)
        governance_bundle = _ensure_node_governance_bundle(node_id)
        governance_version = str(getattr(governance_bundle, "governance_version", "") or "") or None
        policy = node_budget_service.budget_policy(node_id, governance_version=governance_version)
        response.headers["Cache-Control"] = "private, max-age=60"
        return {
            "ok": True,
            "node_id": node_id,
            "governance_version": governance_version,
            "budget_policy_version": policy.get("budget_policy_version"),
            "refresh_interval_s": 60,
            "budget_policy": policy,
        }

    @router.post("/system/nodes/budgets/policy/refresh")
    def refresh_node_budget_policy(
        response: Response,
        body: NodeBudgetPolicyRefreshRequest,
        x_node_trust_token: str | None = Header(default=None),
    ):
        node_id = str(body.node_id or "").strip()
        node_token = str(x_node_trust_token or "").strip()
        if not node_id:
            raise HTTPException(status_code=400, detail={"error": "node_id_required", "message": "node_id is required"})
        if not node_token:
            raise HTTPException(status_code=401, detail="node_trust_token_required")
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")
        if node_trust_issuance.authenticate_node(node_id, node_token) is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})
        registration = node_registrations_store.get(node_id)
        if registration is None or str(registration.trust_status or "").strip().lower() != "trusted":
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not registered"})
        _reject_if_outdated_for_new_contracts(node_id)
        governance_bundle = _ensure_node_governance_bundle(node_id)
        governance_version = str(getattr(governance_bundle, "governance_version", "") or "") or None
        policy = node_budget_service.budget_policy(node_id, governance_version=governance_version)
        response.headers["Cache-Control"] = "private, max-age=5"
        current_budget_policy_version = str(body.current_budget_policy_version or "").strip()
        current_governance_version = str(body.current_governance_version or "").strip()
        if current_budget_policy_version and current_budget_policy_version == str(policy.get("budget_policy_version") or ""):
            if not current_governance_version or current_governance_version == str(governance_version or ""):
                return {
                    "ok": True,
                    "node_id": node_id,
                    "governance_version": governance_version,
                    "budget_policy_version": policy.get("budget_policy_version"),
                    "updated": False,
                    "refresh_interval_s": 60,
                }
        return {
            "ok": True,
            "node_id": node_id,
            "governance_version": governance_version,
            "budget_policy_version": policy.get("budget_policy_version"),
            "updated": True,
            "refresh_interval_s": 60,
            "budget_policy": policy,
        }

    @router.get("/system/nodes/budgets/export")
    def export_node_budget_usage(
        request: Request,
        x_admin_token: str | None = Header(default=None),
        node_id: str | None = Query(default=None),
        format: str = Query(default="json"),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        rows = node_budget_service.export_usage_rows(node_id=node_id)
        fmt = str(format or "json").strip().lower()
        if fmt == "csv":
            output = io.StringIO()
            fieldnames = [
                "node_id",
                "scope_kind",
                "subject_id",
                "period",
                "reset_policy",
                "next_reset_at",
                "money_limit",
                "compute_limit",
                "reserved_money",
                "reserved_compute",
                "actual_money",
                "actual_compute",
                "remaining_money",
                "remaining_compute",
                "money_utilization",
                "compute_utilization",
                "alert_count",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in fieldnames})
            return Response(content=output.getvalue(), media_type="text/csv")
        return {"ok": True, "items": rows}

    @router.get("/system/nodes/budgets/{node_id}")
    def get_node_budget_bundle(
        node_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
        x_node_trust_token: str | None = Header(default=None),
    ):
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        token = str(x_node_trust_token or "").strip()
        if token:
            if node_trust_issuance is None:
                raise HTTPException(status_code=503, detail="trust_issuance_unavailable")
            if node_trust_issuance.authenticate_node(node_id, token) is None:
                raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})
        else:
            require_admin_token(x_admin_token, request)
        try:
            return {"ok": True, "budget": node_budget_service.get_bundle(node_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.put("/system/nodes/budgets/{node_id}")
    async def upsert_node_budget_bundle(
        node_id: str,
        body: NodeBudgetBundleUpsertRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        try:
            bundle = node_budget_service.configure_node_budget(
                node_id=node_id,
                node_budget=body.node_budget.model_dump(mode="json"),
                customer_allocations=[item.model_dump(mode="json") for item in body.customer_allocations],
                provider_allocations=[item.model_dump(mode="json") for item in body.provider_allocations],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc), "message": str(exc)})
        _record_audit(
            audit_store,
            event_type="node_budget_configured",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={
                "node_id": node_id,
                "customer_allocation_count": len(bundle.get("customer_allocations") or []),
                "provider_allocation_count": len(bundle.get("provider_allocations") or []),
            },
        )
        await _publish_budget_policy_snapshot(node_id)
        return {"ok": True, "budget": bundle}

    @router.delete("/system/nodes/budgets/{node_id}")
    async def delete_node_budget_bundle(
        node_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        revocation_payloads = node_budget_service.budget_revocation_payloads(node_id, reason="budget_policy_removed")
        try:
            budget = node_budget_service.delete_node_budget(node_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc), "message": str(exc)})
        _record_audit(
            audit_store,
            event_type="node_budget_deleted",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"node_id": node_id},
        )
        if mqtt_manager is not None:
            for payload in revocation_payloads:
                for topic in node_budget_service.budget_revocation_topics(
                    node_id=node_id,
                    grant_id=str(payload.get("grant_id") or "").strip() or None,
                ):
                    await mqtt_manager.publish(topic=topic, payload=payload, retain=True, qos=1)
        return {"ok": True, "budget": budget}

    @router.get("/system/nodes/budgets/{node_id}/customers")
    def list_customer_budget_allocations(
        node_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        return {"ok": True, "items": node_budget_service.list_allocations(node_id=node_id, kind="customer")}

    @router.put("/system/nodes/budgets/{node_id}/customers/{customer_id}")
    async def upsert_customer_budget_allocation(
        node_id: str,
        customer_id: str,
        body: BudgetAllocationUpsertRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        payload = body.model_dump(mode="json")
        payload["subject_id"] = str(customer_id or "").strip()
        try:
            item = node_budget_service.upsert_allocation(node_id=node_id, kind="customer", payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc), "message": str(exc)})
        _record_audit(
            audit_store,
            event_type="node_budget_customer_allocation_upserted",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"node_id": node_id, "customer_id": customer_id},
        )
        await _publish_budget_policy_snapshot(node_id)
        return {"ok": True, "allocation": item}

    @router.delete("/system/nodes/budgets/{node_id}/customers/{customer_id}")
    async def delete_customer_budget_allocation(
        node_id: str,
        customer_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        try:
            item = node_budget_service.delete_allocation(node_id=node_id, kind="customer", subject_id=customer_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc), "message": str(exc)})
        _record_audit(
            audit_store,
            event_type="node_budget_customer_allocation_deleted",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"node_id": node_id, "customer_id": customer_id},
        )
        await _publish_budget_policy_snapshot(node_id)
        return {"ok": True, "allocation": item}

    @router.get("/system/nodes/budgets/{node_id}/providers")
    def list_provider_budget_allocations(
        node_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        return {"ok": True, "items": node_budget_service.list_allocations(node_id=node_id, kind="provider")}

    @router.put("/system/nodes/budgets/{node_id}/providers/{provider_id}")
    async def upsert_provider_budget_allocation(
        node_id: str,
        provider_id: str,
        body: BudgetAllocationUpsertRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        payload = body.model_dump(mode="json")
        payload["subject_id"] = str(provider_id or "").strip()
        try:
            item = node_budget_service.upsert_allocation(node_id=node_id, kind="provider", payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc), "message": str(exc)})
        _record_audit(
            audit_store,
            event_type="node_budget_provider_allocation_upserted",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"node_id": node_id, "provider_id": provider_id},
        )
        await _publish_budget_policy_snapshot(node_id)
        return {"ok": True, "allocation": item}

    @router.delete("/system/nodes/budgets/{node_id}/providers/{provider_id}")
    async def delete_provider_budget_allocation(
        node_id: str,
        provider_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        try:
            item = node_budget_service.delete_allocation(node_id=node_id, kind="provider", subject_id=provider_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc), "message": str(exc)})
        _record_audit(
            audit_store,
            event_type="node_budget_provider_allocation_deleted",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"node_id": node_id, "provider_id": provider_id},
        )
        await _publish_budget_policy_snapshot(node_id)
        return {"ok": True, "allocation": item}

    @router.get("/system/nodes/budgets/{node_id}/usage")
    def inspect_node_budget_usage(
        node_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        try:
            return {"ok": True, "usage": node_budget_service.usage_inspection(node_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc), "message": str(exc)})

    @router.get("/system/nodes/budgets/{node_id}/usage-reports")
    def list_node_budget_usage_reports(
        node_id: str,
        request: Request,
        grant_id: str | None = Query(default=None),
        service: str | None = Query(default=None),
        provider: str | None = Query(default=None),
        task_family: str | None = Query(default=None),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        try:
            items = node_budget_service.list_usage_reports(node_id=node_id, grant_id=grant_id)
            service_key = str(service or "").strip().lower()
            provider_key = str(provider or "").strip().lower()
            task_family_key = str(task_family or "").strip().lower()
            if service_key:
                items = [item for item in items if str(item.get("service") or "").strip().lower() == service_key]
            if provider_key:
                items = [
                    item
                    for item in items
                    if str((item.get("metadata") or {}).get("provider") or "").strip().lower() == provider_key
                ]
            if task_family_key:
                items = [
                    item
                    for item in items
                    if str((item.get("metadata") or {}).get("task_family") or "").strip().lower() == task_family_key
                ]
            return {"ok": True, "items": items, "rollups": node_budget_service.usage_report_rollups(node_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc), "message": str(exc)})

    @router.post("/system/nodes/budgets/{node_id}/top-up")
    async def top_up_node_budget(
        node_id: str,
        body: NodeBudgetTopUpRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        try:
            budget = node_budget_service.top_up_budget(
                node_id=node_id,
                money_delta=body.money_delta,
                compute_delta=body.compute_delta,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc), "message": str(exc)})
        _record_audit(
            audit_store,
            event_type="node_budget_topped_up",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"node_id": node_id, "money_delta": body.money_delta, "compute_delta": body.compute_delta},
        )
        await _publish_budget_policy_snapshot(node_id)
        return {"ok": True, "budget": budget}

    @router.post("/system/nodes/budgets/{node_id}/reset")
    async def reset_node_budget_usage(
        node_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        try:
            budget = node_budget_service.reset_budget_usage(node_id=node_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc), "message": str(exc)})
        _record_audit(
            audit_store,
            event_type="node_budget_reset",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"node_id": node_id},
        )
        await _publish_budget_policy_snapshot(node_id)
        return {"ok": True, "budget": budget}

    @router.post("/system/nodes/budgets/{node_id}/override")
    async def override_node_budget(
        node_id: str,
        body: NodeBudgetOverrideRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        try:
            budget = node_budget_service.set_temporary_override(
                node_id=node_id,
                enforcement_mode=body.enforcement_mode,
                overcommit_enabled=body.overcommit_enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc), "message": str(exc)})
        _record_audit(
            audit_store,
            event_type="node_budget_override_set",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"node_id": node_id, "enforcement_mode": body.enforcement_mode, "overcommit_enabled": body.overcommit_enabled},
        )
        await _publish_budget_policy_snapshot(node_id)
        return {"ok": True, "budget": budget}

    @router.post("/system/nodes/budgets/{node_id}/force-release")
    def force_release_node_budget_reservation(
        node_id: str,
        body: NodeBudgetForceReleaseRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        try:
            reservation = node_budget_service.force_release_reservation(
                node_id=node_id,
                job_id=body.job_id,
                reservation_id=body.reservation_id,
                reason=str(body.reason or "").strip() or "forced_release",
            )
        except ValueError as exc:
            error = str(exc)
            status_code = 404 if error == "budget_reservation_not_found" else 400
            raise HTTPException(status_code=status_code, detail={"error": error, "message": error})
        _record_audit(
            audit_store,
            event_type="node_budget_reservation_force_released",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"node_id": node_id, "job_id": body.job_id, "reservation_id": body.reservation_id},
        )
        return {"ok": True, "reservation": reservation, "budget": node_budget_service.get_bundle(node_id)}

    @router.post("/system/nodes/budgets/usage-report")
    def report_node_budget_usage(
        body: NodeBudgetUsageReportRequest,
        request: Request,
        x_node_trust_token: str | None = Header(default=None),
    ):
        node_token = str(x_node_trust_token or "").strip()
        if not node_token:
            raise HTTPException(status_code=401, detail="node_trust_token_required")
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")

        node_id = str(body.node_id or "").strip()
        trust_record = node_trust_issuance.authenticate_node(node_id, node_token)
        if trust_record is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})
        registration = node_registrations_store.get(node_id)
        if registration is None or str(registration.trust_status or "").strip().lower() != "trusted":
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not registered"})
        try:
            reservation = node_budget_service.report_actual_usage(
                job_id=str(body.job_id or "").strip(),
                status=str(body.status or "").strip(),
                actual_money_spend=body.actual_money_spend,
                actual_compute_spend=body.actual_compute_spend,
            )
        except ValueError as exc:
            error = str(exc)
            status_code = 404 if error == "budget_reservation_not_found" else 400
            raise HTTPException(status_code=status_code, detail={"error": error, "message": error})
        _record_audit(
            audit_store,
            event_type="node_budget_usage_reported",
            actor_role="node",
            actor_id=node_id,
            details={
                "node_id": node_id,
                "job_id": str(body.job_id or "").strip(),
                "status": str(body.status or "").strip(),
                "source_ip": str(request.client.host if request.client else "unknown"),
            },
        )
        return {"ok": True, "node_id": node_id, "reservation": reservation, "budget": node_budget_service.get_bundle(node_id)}

    @router.post("/system/nodes/budgets/usage-summary")
    def report_node_budget_usage_summary(
        body: NodeBudgetUsageSummaryRequest,
        request: Request,
        x_node_trust_token: str | None = Header(default=None),
    ):
        node_token = str(x_node_trust_token or "").strip()
        if not node_token:
            raise HTTPException(status_code=401, detail="node_trust_token_required")
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")
        node_id = str(body.node_id or "").strip()
        trust_record = node_trust_issuance.authenticate_node(node_id, node_token)
        if trust_record is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})
        registration = node_registrations_store.get(node_id)
        if registration is None or str(registration.trust_status or "").strip().lower() != "trusted":
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not registered"})
        payload = body.model_dump(mode="json")
        payload["error_counts"] = payload.get("error_counts") or {}
        payload["metadata"] = payload.get("metadata") or {}
        try:
            report = node_budget_service.report_usage_summary(node_id=node_id, payload=payload)
        except ValueError as exc:
            error = str(exc)
            raise HTTPException(status_code=400, detail={"error": error, "message": error})
        _record_audit(
            audit_store,
            event_type="node_budget_usage_summary_reported",
            actor_role="node",
            actor_id=node_id,
            details={
                "node_id": node_id,
                "grant_id": str(body.grant_id or "").strip(),
                "service": str(body.service or "").strip() or "ai.inference",
                "source_ip": str(request.client.host if request.client else "unknown"),
            },
        )
        return {"ok": True, "node_id": node_id, "report": report}

    @router.post("/system/nodes/services/resolve")
    async def resolve_node_service(
        body: TaskExecutionResolutionRequest,
        x_node_trust_token: str | None = Header(default=None),
    ):
        node_id = str(body.node_id or "").strip()
        node_token = str(x_node_trust_token or "").strip()
        if not node_id:
            raise HTTPException(status_code=400, detail={"error": "node_id_required", "message": "node_id is required"})
        if not node_token:
            raise HTTPException(status_code=401, detail="node_trust_token_required")
        if node_service_resolution is None:
            raise HTTPException(status_code=503, detail="service_catalog_unavailable")
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        if node_trust_issuance.authenticate_node(node_id, node_token) is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})
        registration = node_registrations_store.get(node_id)
        if registration is None or str(registration.trust_status or "").strip().lower() != "trusted":
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not registered"})
        _reject_if_outdated_for_new_contracts(node_id)
        governance_bundle = _ensure_node_governance_bundle(node_id)
        if governance_bundle is None:
            raise HTTPException(status_code=409, detail={"error": "governance_not_issued", "message": "governance bundle not issued"})
        response_payload = await node_service_resolution.resolve_for_node(
            request=body,
            governance_bundle=governance_bundle.to_dict(),
            budget_service=node_budget_service,
        )
        return {"ok": True, **response_payload.model_dump(mode="json")}

    @router.post("/system/nodes/services/authorize")
    async def authorize_node_service(
        body: NodeServiceAuthorizeRequest,
        request: Request,
        x_node_trust_token: str | None = Header(default=None),
    ):
        node_id = str(body.node_id or "").strip()
        node_token = str(x_node_trust_token or "").strip()
        if not node_id:
            raise HTTPException(status_code=400, detail={"error": "node_id_required", "message": "node_id is required"})
        if not node_token:
            raise HTTPException(status_code=401, detail="node_trust_token_required")
        if node_service_resolution is None:
            raise HTTPException(status_code=503, detail="service_catalog_unavailable")
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")
        if node_budget_service is None:
            raise HTTPException(status_code=503, detail="node_budgeting_unavailable")
        if node_trust_issuance.authenticate_node(node_id, node_token) is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})
        registration = node_registrations_store.get(node_id)
        if registration is None or str(registration.trust_status or "").strip().lower() != "trusted":
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not registered"})
        _reject_if_outdated_for_new_contracts(node_id)
        governance_bundle = _ensure_node_governance_bundle(node_id)
        if governance_bundle is None:
            raise HTTPException(status_code=409, detail={"error": "governance_not_issued", "message": "governance bundle not issued"})
        resolution = await node_service_resolution.resolve_for_node(
            request=TaskExecutionResolutionRequest.model_validate(body.model_dump(mode="json")),
            governance_bundle=governance_bundle.to_dict(),
            budget_service=node_budget_service,
        )
        if not resolution.candidates:
            raise HTTPException(status_code=404, detail={"error": "service_provider_not_found", "message": "no candidate service available"})
        service_id = str(body.service_id or "").strip()
        provider = str(body.provider or body.preferred_provider or "").strip().lower()
        model_id = str(body.model_id or body.preferred_model or "").strip().lower()
        candidate = next(
            (
                item
                for item in resolution.candidates
                if (not service_id or item.service_id == service_id)
                and (not provider or str(item.provider or "").strip().lower() == provider)
                and (not model_id or not item.models_allowed or model_id in [str(v).strip().lower() for v in item.models_allowed])
            ),
            None,
        )
        if candidate is None:
            raise HTTPException(status_code=403, detail={"error": "service_candidate_not_authorized", "message": "requested service candidate not authorized"})
        if candidate.budget_view is None or not bool(candidate.budget_view.admissible):
            raise HTTPException(status_code=403, detail={"error": "budget_not_admissible", "message": "no admissible budget grant available"})
        token, claims = await _issue_service_token_for_node(
            node_id=node_id,
            audience=candidate.service_id,
            scopes=list(candidate.required_scopes or []),
        )
        _record_audit(
            audit_store,
            event_type="node_service_authorized",
            actor_role="node",
            actor_id=node_id,
            details={
                "node_id": node_id,
                "service_id": candidate.service_id,
                "provider": candidate.provider,
                "grant_id": candidate.grant_id,
                "task_family": str(body.task_family or "").strip(),
                "source_ip": str(request.client.host if request.client else "unknown"),
            },
        )
        return {
            "ok": True,
            "node_id": node_id,
            "service_id": candidate.service_id,
            "provider": candidate.provider,
            "model_id": model_id or None,
            "grant_id": candidate.grant_id,
            "required_scopes": list(candidate.required_scopes or []),
            "expires_at": datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc).isoformat(),
            "token": token,
            "claims": claims,
            "resolution": candidate.model_dump(mode="json"),
        }

    @router.post("/system/nodes/providers/capabilities/report")
    def report_provider_capabilities(
        body: ProviderCapabilityReportRequest,
        request: Request,
        x_node_trust_token: str | None = Header(default=None),
    ):
        node_token = str(x_node_trust_token or "").strip()
        if not node_token:
            raise HTTPException(status_code=401, detail="node_trust_token_required")
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")

        node_id = str(body.node_id or "").strip()
        if not node_id:
            raise HTTPException(status_code=400, detail={"error": "node_id_required", "message": "node_id is required"})
        trust_record = node_trust_issuance.authenticate_node(node_id, node_token)
        if trust_record is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})
        registration = node_registrations_store.get(node_id)
        if registration is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not registered"})
        if str(registration.trust_status or "").strip().lower() != "trusted":
            raise HTTPException(
                status_code=403,
                detail={"error": "untrusted_node", "message": f"node trust_status is {registration.trust_status}"},
            )

        try:
            normalized_service_capacity = normalize_capacity_descriptor(body.service_capacity, scope="service")
            normalized_providers, unified_model_descriptors = normalize_provider_capability_report(
                list(body.provider_intelligence or []),
                node_available=bool(body.node_available),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error": str(exc) or "provider_capability_report_invalid", "message": "invalid provider capability report"},
            )

        if normalized_service_capacity:
            normalized_providers = [
                {**dict(item), "service_capacity": dict(normalized_service_capacity)} for item in normalized_providers
            ]
        registration.provider_intelligence = [dict(item) for item in normalized_providers]
        node_registrations_store.upsert(registration)
        if model_routing_registry_service is not None:
            model_routing_registry_service.record_provider_intelligence(
                node_id=node_id,
                provider_intelligence=[dict(item) for item in normalized_providers],
                service_capacity=normalized_service_capacity,
                node_available=bool(body.node_available),
                source="provider_capability_report",
            )

        _record_audit(
            audit_store,
            event_type="node_provider_capability_report_received",
            actor_role="node",
            actor_id=node_id,
            details={
                "node_id": node_id,
                "provider_count": len(normalized_providers),
                "descriptor_count": len(unified_model_descriptors),
                "node_available": bool(body.node_available),
                "service_capacity_declared": bool(normalized_service_capacity),
                "source_ip": str(request.client.host if request.client else "unknown"),
            },
        )
        return {
            "ok": True,
            "node_id": node_id,
            "associated_node_id": registration.node_id,
            "provider_intelligence": [dict(item) for item in normalized_providers],
            "unified_model_descriptors": [dict(item) for item in unified_model_descriptors],
            "service_capacity": normalized_service_capacity,
            "node_available": bool(body.node_available),
            "observed_at": str(body.observed_at or "").strip() or None,
        }

    @router.get("/system/nodes/providers/routing-metadata")
    def list_model_routing_metadata(
        request: Request,
        node_id: str | None = Query(default=None),
        provider: str | None = Query(default=None),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if model_routing_registry_service is None:
            return {"ok": True, "items": [], "nodes": []}
        items = model_routing_registry_service.list(node_id=node_id if node_id else None, provider=provider if provider else None)
        nodes = model_routing_registry_service.list_grouped_by_node(
            node_id=node_id if node_id else None,
            provider=provider if provider else None,
        )
        return {
            "ok": True,
            "items": [item.to_dict() for item in items],
            "nodes": nodes,
        }

    @router.get("/system/nodes/providers/model-policy")
    def list_provider_model_policy(
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if provider_model_policy_service is None:
            return {"ok": True, "items": []}
        items = provider_model_policy_service.list()
        return {"ok": True, "items": [item.to_dict() for item in items]}

    @router.put("/system/nodes/providers/model-policy/{provider}")
    def set_provider_model_policy(
        provider: str,
        body: ProviderModelPolicyUpdateRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if provider_model_policy_service is None:
            raise HTTPException(status_code=503, detail="provider_model_policy_unavailable")
        provider_id = str(provider or "").strip().lower()
        if not provider_id:
            raise HTTPException(status_code=400, detail="provider_required")
        allowed_models = sorted({str(model or "").strip() for model in list(body.allowed_models or []) if str(model or "").strip()})
        record = provider_model_policy_service.set_allowlist(
            provider=provider_id,
            allowed_models=allowed_models,
            updated_by=_admin_actor(x_admin_token),
        )
        _record_audit(
            audit_store,
            event_type="provider_model_policy_updated",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"provider": provider_id, "allowed_model_count": len(allowed_models)},
        )
        return {"ok": True, "policy": record.to_dict()}

    @router.delete("/system/nodes/providers/model-policy/{provider}")
    def delete_provider_model_policy(
        provider: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if provider_model_policy_service is None:
            raise HTTPException(status_code=503, detail="provider_model_policy_unavailable")
        provider_id = str(provider or "").strip().lower()
        if not provider_id:
            raise HTTPException(status_code=400, detail="provider_required")
        removed = provider_model_policy_service.remove_provider(provider_id)
        _record_audit(
            audit_store,
            event_type="provider_model_policy_deleted",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"provider": provider_id, "removed": bool(removed is not None)},
        )
        return {"ok": True, "removed": bool(removed is not None), "provider": provider_id}

    @router.get("/system/nodes/capabilities/profiles")
    def list_node_capability_profiles(
        request: Request,
        node_id: str | None = Query(default=None),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_capability_acceptance is None:
            raise HTTPException(status_code=503, detail="capability_acceptance_unavailable")
        items = node_capability_acceptance.list_profiles(node_id=node_id if node_id else None)
        return {"ok": True, "items": [item.to_dict() for item in items]}

    @router.get("/system/nodes/capabilities/profiles/{profile_id}")
    def get_node_capability_profile(
        profile_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if node_capability_acceptance is None:
            raise HTTPException(status_code=503, detail="capability_acceptance_unavailable")
        item = node_capability_acceptance.get_profile(profile_id)
        if item is None:
            raise HTTPException(status_code=404, detail="node_capability_profile_not_found")
        return {"ok": True, "profile": item.to_dict()}

    @router.get("/system/nodes/governance/current")
    def get_node_governance_bundle(
        response: Response,
        node_id: str = Query(...),
        x_node_trust_token: str | None = Header(default=None),
    ):
        node_key = str(node_id or "").strip()
        node_token = str(x_node_trust_token or "").strip()
        if not node_key:
            raise HTTPException(status_code=400, detail={"error": "node_id_required", "message": "node_id is required"})
        if not node_token:
            raise HTTPException(status_code=401, detail="node_trust_token_required")
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")
        if node_governance_service is None:
            raise HTTPException(status_code=503, detail="node_governance_unavailable")

        trust_record = node_trust_issuance.authenticate_node(node_key, node_token)
        if trust_record is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})

        registration = node_registrations_store.get(node_key)
        if registration is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not registered"})
        if str(registration.trust_status or "").strip().lower() != "trusted":
            raise HTTPException(
                status_code=403,
                detail={"error": "untrusted_node", "message": f"node trust_status is {registration.trust_status}"},
            )
        profile_id = str(registration.capability_profile_id or "").strip()
        if not profile_id:
            raise HTTPException(
                status_code=409,
                detail={"error": "capability_declaration_required", "message": "node capability declaration required"},
            )
        if node_governance_status_service is not None:
            node_governance_status_service.mark_refresh_request(node_id=node_key)
        _observe_governance_freshness(node_key)

        bundle = _ensure_node_governance_bundle(node_key)
        if bundle is not None and str(bundle.capability_profile_id or "").strip() != profile_id:
            bundle = None
        if bundle is None:
            bundle = node_governance_service.get_current_for_node(node_id=node_key, capability_profile_id=profile_id)
        if bundle is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "governance_not_issued", "message": "governance bundle has not been issued yet"},
            )
        refresh_interval = 120
        try:
            refresh_interval = max(30, int(str(os.getenv("SYNTHIA_NODE_GOVERNANCE_REFRESH_INTERVAL_S", "120")).strip()))
        except Exception:
            refresh_interval = 120
        max_age = min(refresh_interval, 300)
        response.headers["Cache-Control"] = f"private, max-age={max_age}"

        return {
            "ok": True,
            "node_id": node_key,
            "capability_profile_id": profile_id,
            "governance_version": bundle.governance_version,
            "issued_timestamp": bundle.issued_timestamp,
            "refresh_interval_s": refresh_interval,
            "governance_bundle": bundle.to_dict(),
        }

    @router.post("/system/nodes/governance/refresh")
    def refresh_node_governance_bundle(
        body: NodeGovernanceRefreshRequest,
        response: Response,
        x_node_trust_token: str | None = Header(default=None),
    ):
        node_key = str(body.node_id or "").strip()
        node_token = str(x_node_trust_token or "").strip()
        if not node_key:
            raise HTTPException(status_code=400, detail={"error": "node_id_required", "message": "node_id is required"})
        if not node_token:
            raise HTTPException(status_code=401, detail="node_trust_token_required")
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")
        if node_governance_service is None:
            raise HTTPException(status_code=503, detail="node_governance_unavailable")

        trust_record = node_trust_issuance.authenticate_node(node_key, node_token)
        if trust_record is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})

        registration = node_registrations_store.get(node_key)
        if registration is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not registered"})
        if str(registration.trust_status or "").strip().lower() != "trusted":
            raise HTTPException(
                status_code=403,
                detail={"error": "untrusted_node", "message": f"node trust_status is {registration.trust_status}"},
            )
        profile_id = str(registration.capability_profile_id or "").strip()
        if not profile_id:
            raise HTTPException(
                status_code=409,
                detail={"error": "capability_declaration_required", "message": "node capability declaration required"},
            )
        if node_governance_status_service is not None:
            node_governance_status_service.mark_refresh_request(node_id=node_key)
        _observe_governance_freshness(node_key)

        bundle = _ensure_node_governance_bundle(node_key)
        if bundle is not None and str(bundle.capability_profile_id or "").strip() != profile_id:
            bundle = None
        if bundle is None:
            bundle = node_governance_service.get_current_for_node(node_id=node_key, capability_profile_id=profile_id)
        if bundle is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "governance_not_issued", "message": "governance bundle has not been issued yet"},
            )
        refresh_interval = 120
        try:
            refresh_interval = max(30, int(str(os.getenv("SYNTHIA_NODE_GOVERNANCE_REFRESH_INTERVAL_S", "120")).strip()))
        except Exception:
            refresh_interval = 120
        response.headers["Cache-Control"] = "private, max-age=5"

        current_version = str(body.current_governance_version or "").strip()
        if current_version and current_version == str(bundle.governance_version or "").strip():
            return {
                "ok": True,
                "node_id": node_key,
                "capability_profile_id": profile_id,
                "governance_version": bundle.governance_version,
                "updated": False,
                "refresh_interval_s": refresh_interval,
            }
        return {
            "ok": True,
            "node_id": node_key,
            "capability_profile_id": profile_id,
            "governance_version": bundle.governance_version,
            "updated": True,
            "refresh_interval_s": refresh_interval,
            "governance_bundle": bundle.to_dict(),
        }

    @router.get("/system/nodes/operational-status/{node_id}")
    async def get_node_operational_status(
        node_id: str,
        request: Request,
        response: Response,
        x_node_trust_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ):
        node_key = str(node_id or "").strip()
        if not node_key:
            raise HTTPException(status_code=400, detail={"error": "node_id_required", "message": "node_id is required"})
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")

        token = str(x_node_trust_token or "").strip()
        if token:
            trust_record = node_trust_issuance.authenticate_node(node_key, token)
            if trust_record is None:
                raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})
        else:
            require_admin_token(x_admin_token, request)

        registration = node_registrations_store.get(node_key)
        if registration is None:
            raise HTTPException(status_code=404, detail="node_registration_not_found")
        _observe_governance_freshness(node_key)
        node_payload = node_registry_payload(registration, node_governance_status_service)
        last_telemetry_timestamp = (
            node_telemetry_service.latest_timestamp(node_key) if node_telemetry_service is not None else None
        )
        response.headers["Cache-Control"] = "private, max-age=15"
        mqtt_runtime_snapshot = None
        status_stale = False
        status_inactive = False
        effective_health_status = None
        last_status_report_at = None
        last_status_age_s = None
        status_freshness_state = "unknown"
        if mqtt_manager is not None:
            snapshot_fn = getattr(mqtt_manager, "node_runtime_snapshot", None)
            if callable(snapshot_fn):
                mqtt_runtime_snapshot = await snapshot_fn(node_key)
        if isinstance(mqtt_runtime_snapshot, dict):
            last_status_report_at = mqtt_runtime_snapshot.get("last_status_report_at")
            effective_health_status = mqtt_runtime_snapshot.get("reported_health_status")
            status_reported_epoch = float(mqtt_runtime_snapshot.get("_last_status_report_epoch") or 0.0)
            if status_reported_epoch > 0.0:
                last_status_age_s = max(0, int(time.time() - status_reported_epoch))
                if last_status_age_s > _node_status_inactive_after_s():
                    status_inactive = True
                    status_stale = True
                    status_freshness_state = "inactive"
                    effective_health_status = "offline"
                elif last_status_age_s > _node_status_stale_after_s():
                    status_stale = True
                    status_freshness_state = "stale"
                    effective_health_status = "degraded"
                else:
                    status_freshness_state = "fresh"
        return {
            "ok": True,
            "node_id": node_key,
            "lifecycle_state": node_payload.get("registry_state"),
            "reported_lifecycle_state": (
                mqtt_runtime_snapshot.get("reported_lifecycle_state")
                if isinstance(mqtt_runtime_snapshot, dict)
                else None
            ),
            "trust_status": node_payload.get("trust_status"),
            "health_status": effective_health_status,
            "status_stale": status_stale,
            "status_inactive": status_inactive,
            "status_freshness_state": status_freshness_state,
            "status_age_s": last_status_age_s,
            "status_stale_after_s": _node_status_stale_after_s(),
            "status_inactive_after_s": _node_status_inactive_after_s(),
            "capability_status": node_payload.get("capability_status"),
            "governance_status": node_payload.get("governance_sync_status"),
            "operational_ready": bool(node_payload.get("operational_ready")),
            "active_governance_version": node_payload.get("active_governance_version"),
            "last_governance_issued_at": node_payload.get("governance_last_issued_at"),
            "last_governance_refresh_request_at": node_payload.get("governance_last_refresh_request_at"),
            "governance_freshness_state": node_payload.get("governance_freshness_state"),
            "governance_freshness_changed_at": node_payload.get("governance_freshness_changed_at"),
            "governance_stale_for_s": node_payload.get("governance_stale_for_s"),
            "governance_outdated": bool(node_payload.get("governance_outdated")),
            "last_telemetry_timestamp": last_telemetry_timestamp,
            "last_lifecycle_report_at": (
                mqtt_runtime_snapshot.get("last_lifecycle_report_at")
                if isinstance(mqtt_runtime_snapshot, dict)
                else None
            ),
            "last_status_report_at": last_status_report_at,
            "updated_at": node_payload.get("updated_at"),
        }

    @router.get("/system/nodes/trust-status/{node_id}")
    def get_node_trust_status(
        node_id: str,
        request: Request,
        response: Response,
        x_node_trust_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ):
        node_key = str(node_id or "").strip()
        if not node_key:
            raise HTTPException(status_code=400, detail={"error": "node_id_required", "message": "node_id is required"})
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")

        token = str(x_node_trust_token or "").strip()
        trust_record = None
        if token:
            trust_record = node_trust_issuance.authenticate_node_any_status(node_key, token)
            if trust_record is None:
                raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})
        else:
            require_admin_token(x_admin_token, request)
            trust_record = node_trust_issuance._store.get_by_node(node_key)
            if trust_record is None:
                raise HTTPException(status_code=404, detail="node_trust_not_found")

        registration = node_registrations_store.get(node_key) if node_registrations_store is not None else None
        response.headers["Cache-Control"] = "private, max-age=5"
        return _node_trust_status_payload(node_id=node_key, trust_record=trust_record, registration=registration)

    @router.post("/system/nodes/telemetry")
    def ingest_node_telemetry(
        body: NodeTelemetryIngestRequest,
        request: Request,
        x_node_trust_token: str | None = Header(default=None),
    ):
        node_key = str(body.node_id or "").strip()
        token = str(x_node_trust_token or "").strip()
        if not node_key:
            raise HTTPException(status_code=400, detail={"error": "node_id_required", "message": "node_id is required"})
        if not token:
            raise HTTPException(status_code=401, detail="node_trust_token_required")
        if node_registrations_store is None:
            raise HTTPException(status_code=503, detail="node_registrations_unavailable")
        if node_trust_issuance is None:
            raise HTTPException(status_code=503, detail="trust_issuance_unavailable")
        if node_telemetry_service is None:
            raise HTTPException(status_code=503, detail="node_telemetry_unavailable")

        trust_record = node_trust_issuance.authenticate_node(node_key, token)
        if trust_record is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not trusted"})
        registration = node_registrations_store.get(node_key)
        if registration is None:
            raise HTTPException(status_code=403, detail={"error": "untrusted_node", "message": "node not registered"})
        if str(registration.trust_status or "").strip().lower() != "trusted":
            raise HTTPException(
                status_code=403,
                detail={"error": "untrusted_node", "message": f"node trust_status is {registration.trust_status}"},
            )
        try:
            event = node_telemetry_service.ingest(
                node_id=node_key,
                event_type=body.event_type,
                event_state=body.event_state,
                message=body.message,
                payload=body.payload if isinstance(body.payload, dict) else {},
            )
        except ValueError as exc:
            error = str(exc)
            if error == "unsupported_event_type":
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "unsupported_event_type",
                        "message": f"supported={','.join(sorted(ALLOWED_NODE_TELEMETRY_EVENTS))}",
                    },
                )
            raise HTTPException(status_code=400, detail={"error": error, "message": error})

        _record_audit(
            audit_store,
            event_type="node_telemetry_ingested",
            actor_role="node",
            actor_id=node_key,
            details={
                "node_id": node_key,
                "event_type": event.event_type,
                "event_state": event.event_state or "",
                "source_ip": str(request.client.host if request.client else "unknown"),
            },
        )
        return {
            "ok": True,
            "node_id": node_key,
            "event_type": event.event_type,
            "received_at": event.received_at,
        }

    @router.delete("/system/nodes/registrations/{node_id}")
    async def delete_node_registration(
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
                trust_removed = bool(
                    node_trust_issuance.revoke_node(
                        node_id,
                        reason="node_removed_by_admin",
                        action="remove",
                    )
                )
            except Exception:
                trust_removed = False
        await _deprovision_node_mqtt_principal(str(node_id or ""), reason=f"node_delete:{node_id}")
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

    @router.post("/system/nodes/registrations/{node_id}/revoke")
    @router.post("/system/nodes/registrations/{node_id}/untrust", include_in_schema=False)
    async def revoke_node_registration(
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
        try:
            updated = node_registrations_store.set_trust_status(node_id, trust_status="revoked")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if updated is None:
            raise HTTPException(status_code=404, detail="node_registration_not_found")
        trust_removed = False
        if node_trust_issuance is not None:
            try:
                trust_removed = bool(
                    node_trust_issuance.revoke_node(
                        node_id,
                        reason="node_trust_revoked_by_admin",
                        action="revoke",
                    )
                )
            except Exception:
                trust_removed = False
        await _deprovision_node_mqtt_principal(str(node_id or ""), reason=f"node_revoke:{node_id}")
        _record_audit(
            audit_store,
            event_type="node_registration_revoked",
            actor_role="admin",
            actor_id=_admin_actor(x_admin_token),
            details={"node_id": str(node_id or ""), "removed_trust_record": trust_removed},
        )
        return {
            "ok": True,
            "registration": node_registry_payload(updated),
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
        requested_node_id = str((session.request_metadata or {}).get("requested_node_id") or "").strip()
        linked_node_id = (
            str(session.linked_node_id or "").strip()
            or requested_node_id
            or _stable_node_id_from_nonce(session.node_nonce)
        )
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
    async def finalize_node_onboarding_session(
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
            replay_activation = None
            if node_trust_issuance is not None:
                try:
                    replay_activation = node_trust_issuance.activation_for_session(session_id)
                except Exception:
                    replay_activation = None
            if isinstance(replay_activation, dict):
                await _provision_node_mqtt_principal(replay_activation)
                return {
                    "ok": True,
                    "onboarding_status": "approved",
                    "activation": replay_activation,
                    "replayed": True,
                }
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
            await _provision_node_mqtt_principal(issued.get("activation"))
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

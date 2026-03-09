from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .authority_policy import validate_authority_topic_access
from .integration_models import (
    MqttAddonGrant,
    MqttBrokerModeSummary,
    MqttPrincipal,
    MqttRegistrationApprovalResult,
    MqttRegistrationRequest,
    MqttSetupCapabilitySummary,
    MqttSetupStateUpdate,
)
from .integration_state import MqttIntegrationStateStore
from .topic_families import is_platform_reserved_topic
from .topic_policy import validate_topic_scopes


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MqttRegistrationApprovalService:
    def __init__(
        self,
        *,
        registry,
        state_store: MqttIntegrationStateStore,
        observability_store=None,
        runtime_reconcile_hook=None,
        audit_store=None,
    ) -> None:
        self._registry = registry
        self._state_store = state_store
        self._observability = observability_store
        self._runtime_reconcile_hook = runtime_reconcile_hook
        self._audit = audit_store

    async def approve(self, request: MqttRegistrationRequest, *, requested_by_subject: str | None = None) -> MqttRegistrationApprovalResult:
        addon_id = request.addon_id.strip()
        if requested_by_subject and requested_by_subject != addon_id:
            return MqttRegistrationApprovalResult(
                addon_id=addon_id or request.addon_id,
                status="rejected",
                access_mode=request.access_mode,
                reason="request_subject_mismatch: service token subject must match addon_id",
            )
        if not addon_id:
            return MqttRegistrationApprovalResult(
                addon_id=request.addon_id,
                status="rejected",
                access_mode=request.access_mode,
                reason="addon_id_required",
            )
        if not self._registry.has_addon(addon_id):
            return MqttRegistrationApprovalResult(
                addon_id=addon_id,
                status="rejected",
                access_mode=request.access_mode,
                reason=f"addon_not_found: '{addon_id}' is not registered in Core",
            )
        if not self._registry.is_enabled(addon_id):
            return MqttRegistrationApprovalResult(
                addon_id=addon_id,
                status="rejected",
                access_mode=request.access_mode,
                reason=f"addon_disabled: '{addon_id}' must be enabled before requesting MQTT access",
            )
        topic_errors = validate_topic_scopes(addon_id, request.publish_topics, request.subscribe_topics)
        if topic_errors:
            await self._record_observability(
                event_type="denied_topic_attempt",
                severity="warn",
                metadata={"addon_id": addon_id, "errors": topic_errors},
            )
            return MqttRegistrationApprovalResult(
                addon_id=addon_id,
                status="rejected",
                access_mode=request.access_mode,
                reason="topic_scope_invalid: " + "; ".join(topic_errors),
            )

        approved = MqttRegistrationApprovalResult(
            addon_id=addon_id,
            status="approved",
            access_mode=request.access_mode,
            approved_publish_topics=sorted({str(x).strip() for x in request.publish_topics if str(x).strip()}),
            approved_subscribe_topics=sorted({str(x).strip() for x in request.subscribe_topics if str(x).strip()}),
        )
        state_before = await self._state_store.get_state()
        existing = state_before.active_grants.get(addon_id)
        grant = MqttAddonGrant(
            addon_id=addon_id,
            access_mode=approved.access_mode,
            status="approved",
            publish_topics=approved.approved_publish_topics,
            subscribe_topics=approved.approved_subscribe_topics,
            granted_ha_mode=request.capabilities.ha_discovery,
            access_profile=approved.access_mode,
            provision_contract=(existing.provision_contract if existing else {}),
            last_error=None,
            revocation_pending=False,
            last_provisioned_at=(existing.last_provisioned_at if existing else None),
            last_revoked_at=(existing.last_revoked_at if existing else None),
        )
        await self._state_store.upsert_grant(grant)
        await self._state_store.upsert_principal(self._principal_from_grant(grant))
        await self._reconcile_runtime_if_needed(reason=f"approve:{addon_id}")
        await self._append_audit(
            event_type="mqtt_principal_action",
            status="ok",
            message="approve_grant",
            payload={"addon_id": addon_id},
        )
        if existing is not None and self._grant_materially_changed(existing, grant) and existing.status in {"approved", "provisioned", "error"}:
            await self.provision_grant(addon_id, reason="grant_scope_changed")
        return approved

    async def provision_grant(self, addon_id: str, reason: str = "api_request") -> dict[str, Any]:
        state = await self._state_store.get_state()
        current = state.active_grants.get(addon_id)
        if current is None:
            return {"ok": False, "addon_id": addon_id, "status": "error", "error": "grant_not_found"}
        if not self._setup_ready(state):
            next_grant = current.model_copy(deep=True)
            next_grant.updated_at = _utcnow_iso()
            next_grant.status = "error"
            next_grant.last_error = f"mqtt_setup_not_ready:{state.setup_status}"
            await self._state_store.upsert_grant(next_grant)
            await self._record_observability(
                event_type="broker_readiness_issue",
                severity="warn",
                metadata={"addon_id": addon_id, "setup_status": state.setup_status},
            )
            return {
                "ok": False,
                "addon_id": addon_id,
                "status": "error",
                "error": "mqtt_setup_not_ready",
                "setup_status": state.setup_status,
            }
        next_grant = current.model_copy(deep=True)
        next_grant.updated_at = _utcnow_iso()
        next_grant.status = "active"
        next_grant.provision_contract = {
            "mode": "embedded_core_authority",
            "reason": reason,
            "applied_at": _utcnow_iso(),
        }
        next_grant.last_error = None
        next_grant.revocation_pending = False
        next_grant.last_provisioned_at = _utcnow_iso()
        await self._state_store.upsert_grant(next_grant)
        principal = self._principal_from_grant(next_grant)
        principal.status = "active"
        principal.last_activated_at = _utcnow_iso()
        await self._state_store.upsert_principal(principal)
        await self._reconcile_runtime_if_needed(reason=f"provision:{addon_id}")
        await self._append_audit(
            event_type="mqtt_principal_action",
            status="ok",
            message="provision_grant",
            payload={"addon_id": addon_id},
        )
        details = {
            "mode": "embedded_core_authority",
            "reason": reason,
            "status": "applied",
        }
        return {"ok": True, "addon_id": addon_id, "status": next_grant.status, "details": details}

    async def revoke_or_mark(self, addon_id: str, reason: str) -> dict[str, Any]:
        state = await self._state_store.get_state()
        current = state.active_grants.get(addon_id)
        if current is None:
            return {"ok": True, "addon_id": addon_id, "status": "not_found"}
        next_grant = current.model_copy(deep=True)
        next_grant.updated_at = _utcnow_iso()
        next_grant.last_revoked_at = _utcnow_iso()
        next_grant.status = "revoked"
        next_grant.last_error = None
        next_grant.revocation_pending = False
        await self._state_store.upsert_grant(next_grant)
        principal = self._principal_from_grant(next_grant)
        principal.status = "revoked"
        principal.last_revoked_at = _utcnow_iso()
        await self._state_store.upsert_principal(principal)
        await self._reconcile_runtime_if_needed(reason=f"revoke:{addon_id}")
        await self._append_audit(
            event_type="mqtt_principal_action",
            status="ok",
            message="revoke_grant",
            payload={"addon_id": addon_id, "reason": reason},
        )
        details = {
            "mode": "embedded_core_authority",
            "reason": reason,
            "status": "revoked",
        }
        return {"ok": True, "addon_id": addon_id, "status": next_grant.status, "details": details}

    async def list_grants(self) -> list[dict[str, Any]]:
        state = await self._state_store.get_state()
        return [item.model_dump(mode="json") for item in sorted(state.active_grants.values(), key=lambda x: x.addon_id)]

    async def get_grant(self, addon_id: str) -> dict[str, Any] | None:
        state = await self._state_store.get_state()
        item = state.active_grants.get(addon_id)
        return item.model_dump(mode="json") if item is not None else None

    async def broker_summary(self) -> MqttBrokerModeSummary:
        state = await self._state_store.get_state()
        return MqttBrokerModeSummary(
            broker_mode=state.broker_mode,
            direct_mqtt_supported=state.direct_mqtt_supported,
        )

    async def setup_summary(self) -> MqttSetupCapabilitySummary:
        state = await self._state_store.get_state()
        return MqttSetupCapabilitySummary(
            requires_setup=state.requires_setup,
            setup_complete=state.setup_complete,
            setup_status=state.setup_status,
            direct_mqtt_supported=state.direct_mqtt_supported,
            setup_error=state.setup_error,
            authority_mode=state.authority_mode,
            authority_ready=state.authority_ready,
            runtime_ready=self._setup_ready(state),
            setup_ready=self._setup_ready(state),
        )

    async def update_setup_state(self, update: MqttSetupStateUpdate) -> MqttSetupCapabilitySummary:
        state = await self._state_store.update_setup_state(update)
        return MqttSetupCapabilitySummary(
            requires_setup=state.requires_setup,
            setup_complete=state.setup_complete,
            setup_status=state.setup_status,
            direct_mqtt_supported=state.direct_mqtt_supported,
            setup_error=state.setup_error,
            authority_mode=state.authority_mode,
            authority_ready=state.authority_ready,
            runtime_ready=self._setup_ready(state),
            setup_ready=self._setup_ready(state),
        )

    async def reconcile(self, addon_id: str) -> dict[str, Any]:
        state = await self._state_store.get_state()
        grant = state.active_grants.get(addon_id)
        if grant is None:
            if self._registry.has_addon(addon_id) and self._registry.is_enabled(addon_id):
                bootstrap = MqttAddonGrant(
                    addon_id=addon_id,
                    access_mode="gateway",
                    status="approved",
                    publish_topics=[f"synthia/addons/{addon_id}/event/#", f"synthia/addons/{addon_id}/state/#"],
                    subscribe_topics=[f"synthia/addons/{addon_id}/command/#", "synthia/bootstrap/core"],
                    granted_ha_mode="disabled",
                    access_profile="gateway",
                )
                await self._state_store.upsert_grant(bootstrap)
                await self._state_store.upsert_principal(self._principal_from_grant(bootstrap))
                await self._reconcile_runtime_if_needed(reason=f"reconcile_bootstrap:{addon_id}")
                return await self.provision_grant(addon_id, reason="onboarding_reconcile")
            return {"ok": True, "addon_id": addon_id, "status": "not_found"}
        if grant.status in {"approved", "error"} and self._registry.is_enabled(addon_id):
            return await self.provision_grant(addon_id, reason="reconcile")
        return {"ok": True, "addon_id": addon_id, "status": grant.status}

    async def list_principals(self) -> list[dict[str, Any]]:
        state = await self._state_store.get_state()
        return [item.model_dump(mode="json") for item in sorted(state.principals.values(), key=lambda x: x.principal_id)]

    async def get_principal(self, principal_id: str) -> dict[str, Any] | None:
        state = await self._state_store.get_state()
        item = state.principals.get(principal_id)
        return item.model_dump(mode="json") if item is not None else None

    async def apply_principal_action(self, principal_id: str, action: str, reason: str | None = None) -> dict[str, Any]:
        state = await self._state_store.get_state()
        principal = state.principals.get(principal_id)
        if principal is None:
            return {"ok": False, "error": "principal_not_found", "principal_id": principal_id}
        next_principal = principal.model_copy(deep=True)
        act = str(action).strip().lower()
        if act == "activate":
            next_principal.status = "active"
            next_principal.last_activated_at = _utcnow_iso()
            next_principal.probation_reason = None
        elif act == "revoke":
            next_principal.status = "revoked"
            next_principal.last_revoked_at = _utcnow_iso()
        elif act == "expire":
            next_principal.status = "expired"
            next_principal.expires_at = _utcnow_iso()
        elif act == "probation":
            next_principal.status = "probation"
            next_principal.probation_reason = reason or "manual_probation"
        elif act == "promote":
            next_principal.status = "active"
            next_principal.last_activated_at = _utcnow_iso()
            next_principal.probation_reason = None
        else:
            return {"ok": False, "error": "principal_action_invalid", "principal_id": principal_id}
        await self._state_store.upsert_principal(next_principal)
        await self._reconcile_runtime_if_needed(reason=f"principal_action:{act}:{principal_id}")
        await self._append_audit(
            event_type="mqtt_principal_action",
            status="ok",
            message=act,
            payload={"principal_id": principal_id, "reason": reason},
        )
        return {"ok": True, "principal": next_principal.model_dump(mode="json")}

    async def create_or_update_generic_user(
        self,
        *,
        principal_id: str,
        logical_identity: str,
        username: str | None,
        publish_topics: list[str],
        subscribe_topics: list[str],
        approved_reserved_topics: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        policy_errors = validate_authority_topic_access(
            principal_type="generic_user",
            publish_topics=publish_topics,
            subscribe_topics=subscribe_topics,
            approved_reserved_topics=approved_reserved_topics or [],
        )
        if policy_errors:
            return {"ok": False, "error": "generic_user_scope_invalid", "details": policy_errors}
        state = await self._state_store.get_state()
        existing = state.principals.get(principal_id)
        principal = (existing.model_copy(deep=True) if existing else MqttPrincipal(
            principal_id=principal_id,
            principal_type="generic_user",
            status="active",
            logical_identity=logical_identity,
        ))
        principal.principal_type = "generic_user"
        principal.logical_identity = logical_identity
        principal.username = username or principal.username
        principal.publish_topics = sorted({topic for topic in publish_topics if topic and not is_platform_reserved_topic(topic)})
        principal.subscribe_topics = sorted({topic for topic in subscribe_topics if topic and not is_platform_reserved_topic(topic)})
        principal.approved_reserved_topics = []
        if principal.status in {"revoked", "expired"}:
            principal.status = "active"
        if notes is not None:
            principal.notes = notes
        principal.last_activated_at = principal.last_activated_at or _utcnow_iso()
        await self._state_store.upsert_principal(principal)
        await self._reconcile_runtime_if_needed(reason=f"generic_user_update:{principal_id}")
        await self._append_audit(
            event_type="mqtt_generic_user_action",
            status="ok",
            message="upsert",
            payload={"principal_id": principal_id},
        )
        return {"ok": True, "principal": principal.model_dump(mode="json")}

    def _grant_materially_changed(self, old: MqttAddonGrant, new: MqttAddonGrant) -> bool:
        if old.access_mode != new.access_mode:
            return True
        if sorted(old.publish_topics) != sorted(new.publish_topics):
            return True
        if sorted(old.subscribe_topics) != sorted(new.subscribe_topics):
            return True
        if old.granted_ha_mode != new.granted_ha_mode:
            return True
        return False

    def _setup_ready(self, state) -> bool:
        if not state.mqtt_enabled:
            return False
        if state.requires_setup:
            return state.setup_complete and state.setup_status == "ready" and state.authority_ready
        return state.authority_ready

    def _principal_from_grant(self, grant: MqttAddonGrant) -> MqttPrincipal:
        approved_reserved_topics = [
            topic for topic in list(grant.publish_topics) + list(grant.subscribe_topics) if is_platform_reserved_topic(topic)
        ]
        return MqttPrincipal(
            principal_id=f"addon:{grant.addon_id}",
            principal_type="synthia_addon",
            status=("active" if grant.status == "active" else "pending"),
            logical_identity=grant.addon_id,
            linked_addon_id=grant.addon_id,
            publish_topics=sorted({str(topic).strip() for topic in grant.publish_topics if str(topic).strip()}),
            subscribe_topics=sorted({str(topic).strip() for topic in grant.subscribe_topics if str(topic).strip()}),
            approved_reserved_topics=sorted({str(topic).strip() for topic in approved_reserved_topics if str(topic).strip()}),
            notes=f"created_from_grant:{grant.access_mode}",
        )

    async def _record_observability(self, *, event_type: str, severity: str, metadata: dict[str, Any]) -> None:
        if self._observability is None:
            return
        try:
            await self._observability.append_event(
                event_type=event_type,
                source="mqtt_approval",
                severity=severity,
                metadata=metadata,
            )
        except Exception:
            return

    async def _reconcile_runtime_if_needed(self, *, reason: str) -> None:
        if self._runtime_reconcile_hook is None:
            return
        try:
            await self._runtime_reconcile_hook(reason=reason)
        except Exception:
            await self._record_observability(
                event_type="broker_readiness_issue",
                severity="warn",
                metadata={"reason": reason, "error": "runtime_reconcile_failed"},
            )

    async def _append_audit(self, *, event_type: str, status: str, message: str, payload: dict[str, Any]) -> None:
        if self._audit is None:
            return
        try:
            await self._audit.append_event(event_type=event_type, status=status, message=message, payload=payload)
        except Exception:
            return

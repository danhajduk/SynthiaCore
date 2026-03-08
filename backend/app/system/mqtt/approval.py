from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from .integration_models import (
    MqttAddonGrant,
    MqttBrokerModeSummary,
    MqttRegistrationApprovalResult,
    MqttRegistrationRequest,
    MqttSetupCapabilitySummary,
)
from .integration_state import MqttIntegrationStateStore
from .topic_policy import validate_topic_scopes


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MqttRegistrationApprovalService:
    def __init__(self, *, registry, state_store: MqttIntegrationStateStore) -> None:
        self._registry = registry
        self._state_store = state_store
        self._control_addon_id = os.getenv("SYNTHIA_MQTT_CONTROL_ADDON_ID", "mqtt").strip() or "mqtt"
        self._provision_path = os.getenv("SYNTHIA_MQTT_PROVISION_PATH", "/api/addon/mqtt/provision").strip() or "/api/addon/mqtt/provision"
        self._revoke_path = os.getenv("SYNTHIA_MQTT_REVOKE_PATH", "/api/addon/mqtt/revoke").strip() or "/api/addon/mqtt/revoke"
        self._internal_token = os.getenv("SYNTHIA_INTERNAL_MQTT_TOKEN", "").strip()
        self._timeout_s = float(os.getenv("SYNTHIA_MQTT_PROVISION_TIMEOUT_S", "8") or 8)

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
        await self._state_store.upsert_grant(
            MqttAddonGrant(
                addon_id=addon_id,
                access_mode=approved.access_mode,
                status="approved",
                publish_topics=approved.approved_publish_topics,
                subscribe_topics=approved.approved_subscribe_topics,
                granted_ha_mode=request.capabilities.ha_discovery,
                access_profile=approved.access_mode,
            )
        )
        return approved

    async def provision_grant(self, addon_id: str, reason: str = "api_request") -> dict[str, Any]:
        state = await self._state_store.get_state()
        current = state.active_grants.get(addon_id)
        if current is None:
            return {"ok": False, "addon_id": addon_id, "status": "error", "error": "grant_not_found"}
        payload = {
            "addon_id": current.addon_id,
            "approved_publish_scopes": list(current.publish_topics),
            "approved_subscribe_scopes": list(current.subscribe_topics),
            "granted_ha_mode": current.granted_ha_mode,
            "access_profile": current.access_profile,
            "reason": reason,
        }
        ok, details = await self._call_control_plane(path=self._provision_path, payload=payload)
        next_grant = current.model_copy(deep=True)
        next_grant.updated_at = _utcnow_iso()
        if ok:
            next_grant.status = "provisioned"
            next_grant.provision_contract = details
            next_grant.last_error = None
            next_grant.revocation_pending = False
            next_grant.last_provisioned_at = _utcnow_iso()
        else:
            next_grant.status = "error"
            next_grant.last_error = str(details.get("error") or "provision_failed")
        await self._state_store.upsert_grant(next_grant)
        return {"ok": ok, "addon_id": addon_id, "status": next_grant.status, "details": details}

    async def revoke_or_mark(self, addon_id: str, reason: str) -> dict[str, Any]:
        state = await self._state_store.get_state()
        current = state.active_grants.get(addon_id)
        if current is None:
            return {"ok": True, "addon_id": addon_id, "status": "not_found"}
        payload = {
            "addon_id": addon_id,
            "reason": reason,
            "access_mode": current.access_mode,
            "publish_topics": current.publish_topics,
            "subscribe_topics": current.subscribe_topics,
        }
        ok, details = await self._call_control_plane(path=self._revoke_path, payload=payload)
        next_grant = current.model_copy(deep=True)
        next_grant.updated_at = _utcnow_iso()
        next_grant.last_revoked_at = _utcnow_iso()
        if ok:
            next_grant.status = "revoked"
            next_grant.last_error = None
            next_grant.revocation_pending = False
        else:
            next_grant.status = "error"
            next_grant.last_error = str(details.get("error") or "revoke_failed")
            next_grant.revocation_pending = True
        await self._state_store.upsert_grant(next_grant)
        return {"ok": ok, "addon_id": addon_id, "status": next_grant.status, "details": details}

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
            requires_setup=True,
            setup_complete=state.setup_status == "ready",
            setup_status=state.setup_status,
            direct_mqtt_supported=state.direct_mqtt_supported,
        )

    def _control_base_url(self) -> str | None:
        addon = self._registry.registered.get(self._control_addon_id)
        if addon is None:
            return None
        return str(addon.base_url or "").rstrip("/") or None

    async def _call_control_plane(self, *, path: str, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        base = self._control_base_url()
        if not base:
            return False, {"error": "mqtt_control_addon_not_registered"}
        url = f"{base}{path}"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._internal_token:
            headers["X-Synthia-Core-Auth"] = self._internal_token
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout_s), follow_redirects=False) as client:
                resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                return False, {"error": f"provision_http_{resp.status_code}", "url": url, "body": resp.text}
            try:
                body = resp.json()
                details = body if isinstance(body, dict) else {"result": body}
            except Exception:
                details = {"result": resp.text}
            details["url"] = url
            return True, details
        except Exception as exc:
            return False, {"error": type(exc).__name__, "url": url}

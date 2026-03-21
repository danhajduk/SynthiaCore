from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

from .integration_models import MqttAddonGrant, MqttIntegrationState, MqttPrincipal, MqttSetupStateUpdate
from .topic_families import normalize_legacy_topic_namespace


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MqttIntegrationStateStore:
    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = asyncio.Lock()

    async def get_state(self) -> MqttIntegrationState:
        async with self._lock:
            return await asyncio.to_thread(self._read_sync)

    async def replace_state(self, state: MqttIntegrationState) -> MqttIntegrationState:
        async with self._lock:
            payload = state.model_copy(update={"updated_at": _utcnow_iso()})
            await asyncio.to_thread(self._write_sync, payload)
            return payload

    async def upsert_grant(self, grant: MqttAddonGrant) -> MqttIntegrationState:
        async with self._lock:
            state = await asyncio.to_thread(self._read_sync)
            next_grant = grant.model_copy(update={"updated_at": _utcnow_iso()})
            grants = dict(state.active_grants)
            grants[next_grant.addon_id] = next_grant
            next_state = state.model_copy(update={"active_grants": grants, "updated_at": _utcnow_iso()})
            await asyncio.to_thread(self._write_sync, next_state)
            return next_state

    async def upsert_principal(self, principal: MqttPrincipal) -> MqttIntegrationState:
        async with self._lock:
            state = await asyncio.to_thread(self._read_sync)
            next_principal = principal.model_copy(update={"updated_at": _utcnow_iso()})
            principals = dict(state.principals)
            principals[next_principal.principal_id] = next_principal
            next_state = state.model_copy(update={"principals": principals, "updated_at": _utcnow_iso()})
            await asyncio.to_thread(self._write_sync, next_state)
            return next_state

    async def remove_principal(self, principal_id: str) -> MqttIntegrationState:
        async with self._lock:
            state = await asyncio.to_thread(self._read_sync)
            principals = dict(state.principals)
            principals.pop(principal_id, None)
            next_state = state.model_copy(update={"principals": principals, "updated_at": _utcnow_iso()})
            await asyncio.to_thread(self._write_sync, next_state)
            return next_state

    async def update_setup_state(self, setup: MqttSetupStateUpdate) -> MqttIntegrationState:
        async with self._lock:
            state = await asyncio.to_thread(self._read_sync)
            next_state = state.model_copy(
                update={
                    "requires_setup": setup.requires_setup,
                    "setup_complete": setup.setup_complete,
                    "setup_status": setup.setup_status,
                    "broker_mode": setup.broker_mode,
                    "direct_mqtt_supported": setup.direct_mqtt_supported,
                    "setup_error": setup.setup_error,
                    "authority_mode": setup.authority_mode,
                    "authority_ready": setup.authority_ready,
                    "updated_at": _utcnow_iso(),
                }
            )
            await asyncio.to_thread(self._write_sync, next_state)
            return next_state

    def _read_sync(self) -> MqttIntegrationState:
        if not os.path.exists(self.path):
            return MqttIntegrationState()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return MqttIntegrationState()
            state = MqttIntegrationState.model_validate(raw)
            normalized = self._normalize_state_topics(state)
            if normalized != state:
                self._write_sync(normalized)
            return normalized
        except Exception:
            return MqttIntegrationState()

    def _write_sync(self, state: MqttIntegrationState) -> None:
        normalized = self._normalize_state_topics(state)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(normalized.model_dump(mode="json"), f, indent=2, sort_keys=True)

    @staticmethod
    def _normalize_topics(items: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = normalize_legacy_topic_namespace(str(item or "").strip())
            if normalized and normalized not in seen:
                out.append(normalized)
                seen.add(normalized)
        return out

    @classmethod
    def _normalize_state_topics(cls, state: MqttIntegrationState) -> MqttIntegrationState:
        grants = {
            addon_id: grant.model_copy(
                update={
                    "publish_topics": cls._normalize_topics(list(grant.publish_topics or [])),
                    "subscribe_topics": cls._normalize_topics(list(grant.subscribe_topics or [])),
                }
            )
            for addon_id, grant in state.active_grants.items()
        }
        principals = {
            principal_id: principal.model_copy(
                update={
                    "publish_topics": cls._normalize_topics(list(principal.publish_topics or [])),
                    "subscribe_topics": cls._normalize_topics(list(principal.subscribe_topics or [])),
                    "allowed_topics": cls._normalize_topics(list(principal.allowed_topics or [])),
                    "allowed_publish_topics": cls._normalize_topics(list(principal.allowed_publish_topics or [])),
                    "allowed_subscribe_topics": cls._normalize_topics(list(principal.allowed_subscribe_topics or [])),
                    "approved_reserved_topics": cls._normalize_topics(list(principal.approved_reserved_topics or [])),
                    "topic_prefix": normalize_legacy_topic_namespace(str(principal.topic_prefix or "").strip()) or None,
                }
            )
            for principal_id, principal in state.principals.items()
        }
        return state.model_copy(update={"active_grants": grants, "principals": principals})

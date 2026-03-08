from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

from .integration_models import MqttAddonGrant, MqttIntegrationState, MqttSetupStateUpdate


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
            return MqttIntegrationState.model_validate(raw)
        except Exception:
            return MqttIntegrationState()

    def _write_sync(self, state: MqttIntegrationState) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(state.model_dump(mode="json"), f, indent=2, sort_keys=True)

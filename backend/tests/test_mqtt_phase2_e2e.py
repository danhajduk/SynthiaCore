import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.addons.models import AddonMeta, BackendAddon, RegisteredAddon
from app.addons.registry import AddonRegistry
from app.system.auth import ServiceTokenKeyStore
from app.system.mqtt.acl_compiler import MqttAclCompiler
from app.system.mqtt.approval import MqttRegistrationApprovalService
from app.system.mqtt.authority_audit import MqttAuthorityAuditStore
from app.system.mqtt.credential_store import MqttCredentialStore
from app.system.mqtt.integration_state import MqttIntegrationStateStore
from app.system.mqtt.observability_store import MqttObservabilityStore
from app.system.mqtt.router import build_mqtt_router


class _FakeSettingsStore:
    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    async def get(self, key: str):
        return self._data.get(key)


class _FakeMqttManager:
    async def status(self):
        return {
            "ok": True,
            "enabled": True,
            "connected": True,
            "last_message_at": None,
            "last_error": None,
            "connection_count": 3,
            "auth_failures": 0,
            "reconnect_spikes": 0,
        }

    async def restart(self):
        return None

    async def publish_test(self, topic: str | None = None, payload: dict | None = None):
        return {"ok": True, "topic": topic or "synthia/core/mqtt/info", "payload": payload or {}}


class _FakeRuntimeReconciler:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def reconcile_authority(self, *, reason: str):
        self.calls.append(reason)
        return None

    def reconciliation_status(self):
        return {
            "last_reconcile_at": "2026-03-09T10:00:00Z",
            "last_reconcile_reason": self.calls[-1] if self.calls else "startup",
            "last_reconcile_status": "ok",
            "last_reconcile_error": None,
            "last_runtime_state": "running",
        }

    def bootstrap_status(self):
        return {
            "attempts": 1,
            "successes": 1,
            "last_attempt_at": "2026-03-09T10:00:00Z",
            "last_success_at": "2026-03-09T10:00:00Z",
            "last_error": None,
            "published": True,
        }


class TestMqttPhase2E2E(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(os.environ, {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False)
        self.env_patch.start()
        self.tmpdir = tempfile.TemporaryDirectory()
        base = Path(self.tmpdir.name)
        self.settings = _FakeSettingsStore()
        self.key_store = ServiceTokenKeyStore(self.settings)
        self.state_store = MqttIntegrationStateStore(str(base / "mqtt_state.json"))
        self.credential_store = MqttCredentialStore(str(base / "mqtt_credentials.json"))
        self.observability = MqttObservabilityStore(str(base / "mqtt_observability.db"))
        self.audit = MqttAuthorityAuditStore(str(base / "mqtt_audit.db"))
        self.runtime = _FakeRuntimeReconciler()
        self.registry = AddonRegistry(
            addons={
                "vision": BackendAddon(
                    meta=AddonMeta(id="vision", name="Vision", version="1.0.0"),
                    router=APIRouter(),
                )
            },
            errors={},
            enabled={"vision": True},
            registered={
                "mqtt": RegisteredAddon(
                    id="mqtt",
                    name="MQTT",
                    version="1.0.0",
                    base_url="http://mqtt-addon.local:9100",
                )
            },
        )
        self.approval = MqttRegistrationApprovalService(
            registry=self.registry,
            state_store=self.state_store,
            runtime_reconcile_hook=self.runtime.reconcile_authority,
            observability_store=self.observability,
            audit_store=self.audit,
            credential_rotate_hook=self.credential_store.rotate_principal,
        )
        app = FastAPI()
        app.include_router(
            build_mqtt_router(
                _FakeMqttManager(),
                self.registry,
                self.state_store,
                self.key_store,
                approval_service=self.approval,
                acl_compiler=MqttAclCompiler(),
                credential_store=self.credential_store,
                runtime_reconciler=self.runtime,
                observability_store=self.observability,
                audit_store=self.audit,
            ),
            prefix="/api/system",
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()
        self.env_patch.stop()

    def test_phase2_lifecycle_and_runtime_access_controls(self) -> None:
        setup_ready = self.client.post(
            "/api/system/mqtt/setup-state",
            headers={"X-Admin-Token": "test-token"},
            json={
                "requires_setup": True,
                "setup_complete": True,
                "setup_status": "ready",
                "broker_mode": "local",
                "direct_mqtt_supported": True,
                "authority_ready": True,
                "setup_error": None,
            },
        )
        self.assertEqual(setup_ready.status_code, 200, setup_ready.text)

        approved = self.client.post(
            "/api/system/mqtt/registrations/approve",
            headers={"X-Admin-Token": "test-token"},
            json={
                "addon_id": "vision",
                "access_mode": "gateway",
                "publish_topics": ["synthia/addons/vision/event/#"],
                "subscribe_topics": ["synthia/addons/vision/command/#"],
            },
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertTrue(approved.json()["ok"])

        provisioned = self.client.post(
            "/api/system/mqtt/registrations/vision/provision",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(provisioned.status_code, 200, provisioned.text)
        self.assertEqual(provisioned.json()["status"], "active")

        principals = self.client.get("/api/system/mqtt/principals", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(principals.status_code, 200, principals.text)
        addon_principal = {item["principal_id"]: item for item in principals.json()["items"]}["addon:vision"]
        self.assertEqual(addon_principal["principal_type"], "synthia_addon")
        self.assertEqual(addon_principal["status"], "active")

        addon_access = self.client.get(
            "/api/system/mqtt/debug/effective-access/addon:vision",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(addon_access.status_code, 200, addon_access.text)
        self.assertIn("synthia/addons/vision/event/#", addon_access.json()["effective_access"]["publish_scopes"])

        created = asyncio.run(
            self.approval.create_or_update_generic_user(
                principal_id="user:guest-e2e",
                logical_identity="guest-e2e",
                username="guest-e2e",
                publish_topics=["devices/guest-e2e/state"],
                subscribe_topics=["devices/guest-e2e/cmd"],
                notes="phase2_e2e",
            )
        )
        self.assertTrue(created["ok"])

        generic_effective = self.client.get(
            "/api/system/mqtt/generic-users/user:guest-e2e/effective-access",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(generic_effective.status_code, 200, generic_effective.text)
        effective_payload = generic_effective.json()["effective_access"]
        self.assertEqual(effective_payload["publish_scopes"], ["devices/guest-e2e/state"])
        self.assertEqual(effective_payload["subscribe_scopes"], ["devices/guest-e2e/cmd"])
        self.assertTrue(effective_payload["generic_non_reserved_only"])

        watch = self.client.post(
            "/api/system/mqtt/noisy-clients/user:guest-e2e/actions/mark_watch",
            headers={"X-Admin-Token": "test-token"},
            json={"reason": "phase2_watch"},
        )
        self.assertEqual(watch.status_code, 200, watch.text)
        self.assertEqual(watch.json()["principal"]["noisy_state"], "watch")

        quarantine = self.client.post(
            "/api/system/mqtt/noisy-clients/user:guest-e2e/actions/quarantine",
            headers={"X-Admin-Token": "test-token"},
            json={"reason": "phase2_quarantine"},
        )
        self.assertEqual(quarantine.status_code, 200, quarantine.text)
        self.assertEqual(quarantine.json()["principal"]["noisy_state"], "blocked")
        self.assertEqual(quarantine.json()["principal"]["status"], "probation")

        blocked_effective = self.client.get(
            "/api/system/mqtt/debug/effective-access/user:guest-e2e",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(blocked_effective.status_code, 200, blocked_effective.text)
        blocked_payload = blocked_effective.json()["effective_access"]
        self.assertEqual(blocked_payload["publish_scopes"], [])
        self.assertEqual(blocked_payload["subscribe_scopes"], [])

        rotated = self.client.post(
            "/api/system/mqtt/generic-users/user:guest-e2e/rotate-credentials",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(rotated.status_code, 200, rotated.text)
        self.assertIn("rotated", rotated.json())

        cleared = self.client.post(
            "/api/system/mqtt/noisy-clients/user:guest-e2e/actions/clear",
            headers={"X-Admin-Token": "test-token"},
            json={"reason": "phase2_clear"},
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(cleared.json()["principal"]["noisy_state"], "normal")
        self.assertEqual(cleared.json()["principal"]["status"], "active")

        revoked = self.client.post(
            "/api/system/mqtt/generic-users/user:guest-e2e/revoke",
            headers={"X-Admin-Token": "test-token"},
            json={"reason": "phase2_manual_revoke"},
        )
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(revoked.json()["principal"]["status"], "revoked")

        revoked_effective = self.client.get(
            "/api/system/mqtt/debug/effective-access/user:guest-e2e",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(revoked_effective.status_code, 404, revoked_effective.text)

        noisy_list = self.client.get("/api/system/mqtt/noisy-clients", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(noisy_list.status_code, 200, noisy_list.text)
        self.assertIsInstance(noisy_list.json()["items"], list)

        audit_events = self.client.get("/api/system/mqtt/audit?limit=20", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(audit_events.status_code, 200, audit_events.text)
        self.assertGreaterEqual(len(audit_events.json()["items"]), 3)

        observability_events = self.client.get(
            "/api/system/mqtt/observability?limit=20",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(observability_events.status_code, 200, observability_events.text)
        self.assertIsInstance(observability_events.json()["items"], list)


if __name__ == "__main__":
    unittest.main()

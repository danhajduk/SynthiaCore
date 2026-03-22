import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.system import build_system_router
    FASTAPI_STACK_AVAILABLE = True
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None
    build_system_router = None
    FASTAPI_STACK_AVAILABLE = False

from app.system.onboarding import NodeOnboardingSessionsStore, NodeRegistrationsStore, NodeTrustIssuanceService, NodeTrustStore
from app.system.mqtt.credential_store import MqttCredentialStore
from app.system.mqtt.integration_state import MqttIntegrationStateStore
from app.api import system as system_api


class _FakeRegistry:
    def has_addon(self, addon_id: str) -> bool:
        return False

    def is_platform_managed(self, addon_id: str) -> bool:
        return False

    def set_enabled(self, addon_id: str, enabled: bool) -> None:
        return None

    def is_enabled(self, addon_id: str) -> bool:
        return False

    @property
    def errors(self):
        return []


class _FakeRuntimeReconciler:
    def __init__(self) -> None:
        self.reasons: list[str] = []

    async def reconcile_authority(self, *, reason: str, **kwargs):
        self.reasons.append(str(reason))
        return {"ok": True}


@unittest.skipIf(not FASTAPI_STACK_AVAILABLE, "fastapi/testclient not available in this environment")
class TestNodeRegistrationsApi(unittest.TestCase):
    def setUp(self) -> None:
        system_api._RATE_WINDOWS.clear()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sessions = NodeOnboardingSessionsStore(path=Path(self.tmpdir.name) / "node_onboarding_sessions.json")
        self.registrations = NodeRegistrationsStore(path=Path(self.tmpdir.name) / "node_registrations.json")
        self.trust_store = NodeTrustStore(path=Path(self.tmpdir.name) / "node_trust_records.json")
        self.trust_issuance = NodeTrustIssuanceService(self.trust_store)
        self.mqtt_state_store = MqttIntegrationStateStore(str(Path(self.tmpdir.name) / "mqtt_integration_state.json"))
        self.mqtt_credential_store = MqttCredentialStore(str(Path(self.tmpdir.name) / "mqtt_credentials.json"))
        self.runtime_reconciler = _FakeRuntimeReconciler()
        app = FastAPI()
        app.include_router(
            build_system_router(
                _FakeRegistry(),
                mqtt_integration_state_store=self.mqtt_state_store,
                mqtt_credential_store=self.mqtt_credential_store,
                mqtt_runtime_reconciler=self.runtime_reconciler,
                onboarding_sessions_store=self.sessions,
                node_registrations_store=self.registrations,
                node_trust_issuance=self.trust_issuance,
            ),
            prefix="/api",
        )
        self.client = TestClient(app)
        self.env_patch = patch.dict(
            os.environ,
            {
                "SYNTHIA_AI_NODE_ONBOARDING_ENABLED": "true",
                "SYNTHIA_AI_NODE_ONBOARDING_PROTOCOLS": "1.0",
                "SYNTHIA_NODE_ONBOARDING_SUPPORTED_TYPES": "ai-node,sensor-node",
                "SYNTHIA_ADMIN_TOKEN": "test-token",
            },
            clear=False,
        )
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.tmpdir.cleanup()

    def _start_and_approve(self, node_name: str, node_type: str, nonce: str) -> dict:
        started = self.client.post(
            "/api/system/nodes/onboarding/sessions",
            json={
                "node_name": node_name,
                "node_type": node_type,
                "node_software_version": "1.0.0",
                "protocol_version": "1.0",
                "ui_endpoint": f"http://{node_name}.local:8765/ui",
                "node_nonce": nonce,
            },
        )
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]
        state = started.json()["session"]["approval_url"].split("state=", 1)[1]
        approve = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/approve?state={state}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(approve.status_code, 200, approve.text)
        return approve.json()["registration"]

    def test_list_and_get_registrations(self) -> None:
        created = self._start_and_approve("office-node", "ai-node", "nonce-api-1")
        node_id = created["node_id"]

        listed = self.client.get("/api/system/nodes/registrations", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(listed.status_code, 200, listed.text)
        items = listed.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["node_id"], node_id)
        self.assertEqual(items[0]["trust_status"], "approved")
        self.assertEqual(items[0]["source_onboarding_session_id"], created["source_onboarding_session_id"])
        self.assertEqual(items[0]["requested_ui_endpoint"], "http://office-node.local:8765/ui")
        self.assertTrue(items[0]["ui_enabled"])
        self.assertEqual(items[0]["ui_base_url"], "http://office-node.local:8765/ui")
        self.assertEqual(items[0]["ui_mode"], "spa")
        self.assertIsNone(items[0]["ui_health_endpoint"])

        got = self.client.get(f"/api/system/nodes/registrations/{node_id}", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(got.status_code, 200, got.text)
        registration = got.json()["registration"]
        self.assertEqual(registration["node_type"], "ai")
        self.assertEqual(registration["requested_node_type"], "ai-node")
        self.assertEqual(registration["requested_ui_endpoint"], "http://office-node.local:8765/ui")
        self.assertTrue(registration["ui_enabled"])
        self.assertEqual(registration["ui_base_url"], "http://office-node.local:8765/ui")
        self.assertEqual(registration["ui_mode"], "spa")
        self.assertIsNone(registration["ui_health_endpoint"])

    def test_finalize_marks_registration_trusted(self) -> None:
        started = self.client.post(
            "/api/system/nodes/onboarding/sessions",
            json={
                "node_name": "trust-node",
                "node_type": "ai-node",
                "node_software_version": "1.0.0",
                "protocol_version": "1.0",
                "node_nonce": "nonce-api-4",
            },
        )
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]
        state = started.json()["session"]["approval_url"].split("state=", 1)[1]
        approve = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/approve?state={state}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(approve.status_code, 200, approve.text)
        node_id = approve.json()["registration"]["node_id"]

        finalized = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-api-4"
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        self.assertEqual(finalized.json()["onboarding_status"], "approved")
        self.assertEqual(finalized.json()["activation"]["node_type"], "ai-node")

        got = self.client.get(f"/api/system/nodes/registrations/{node_id}", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["registration"]["trust_status"], "trusted")

    def test_finalize_provisions_node_mqtt_principal_and_credentials(self) -> None:
        created = self._start_and_approve("mqtt-node", "ai-node", "nonce-mqtt-1")
        node_id = created["node_id"]
        session_id = created["source_onboarding_session_id"]
        finalized = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-mqtt-1"
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        activation = finalized.json()["activation"]
        self.assertTrue(str(activation["operational_mqtt_identity"]).startswith("hn_"))

        state = self.mqtt_state_store._read_sync()
        principal = state.principals.get(f"node:{node_id}")
        self.assertIsNotNone(principal)
        self.assertEqual(principal.principal_type, "synthia_node")
        self.assertEqual(principal.status, "active")
        self.assertEqual(principal.username, activation["operational_mqtt_identity"])
        self.assertEqual(principal.publish_topics, [f"hexe/nodes/{node_id}/#"])
        self.assertEqual(principal.subscribe_topics, ["hexe/bootstrap/core", f"hexe/nodes/{node_id}/#"])

        credential = self.mqtt_credential_store.get_principal_credential(f"node:{node_id}")
        self.assertIsNotNone(credential)
        self.assertEqual(credential["username"], activation["operational_mqtt_identity"])
        self.assertEqual(credential["password"], activation["operational_mqtt_token"])
        self.assertIn(f"node_finalize:{node_id}", self.runtime_reconciler.reasons)

    def test_finalize_consumed_replay_returns_activation_and_reprovisions(self) -> None:
        created = self._start_and_approve("mqtt-replay-node", "ai-node", "nonce-mqtt-replay-1")
        node_id = created["node_id"]
        session_id = created["source_onboarding_session_id"]

        first = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-mqtt-replay-1"
        )
        self.assertEqual(first.status_code, 200, first.text)
        activation = first.json()["activation"]
        self.assertTrue(str(activation["operational_mqtt_identity"]).startswith("hn_"))

        second = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-mqtt-replay-1"
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["onboarding_status"], "approved")
        self.assertTrue(second.json().get("replayed"))
        self.assertEqual(second.json()["activation"]["node_id"], node_id)

        credential = self.mqtt_credential_store.get_principal_credential(f"node:{node_id}")
        self.assertIsNotNone(credential)
        self.assertEqual(credential["username"], second.json()["activation"]["operational_mqtt_identity"])
        self.assertGreaterEqual(
            len([item for item in self.runtime_reconciler.reasons if item == f"node_finalize:{node_id}"]),
            2,
        )

    def test_list_registrations_filters(self) -> None:
        self._start_and_approve("office-node", "ai-node", "nonce-api-2")
        self._start_and_approve("sensor-west", "sensor-node", "nonce-api-3")

        filtered_type = self.client.get(
            "/api/system/nodes/registrations?node_type=sensor-node",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(filtered_type.status_code, 200, filtered_type.text)
        items = filtered_type.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["node_type"], "sensor")

        filtered_status = self.client.get(
            "/api/system/nodes/registrations?trust_status=approved",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(filtered_status.status_code, 200, filtered_status.text)
        self.assertEqual(len(filtered_status.json()["items"]), 2)

    def test_node_registry_view_model_filters(self) -> None:
        first = self._start_and_approve("office-node", "ai-node", "nonce-registry-1")
        second = self._start_and_approve("sensor-west", "sensor-node", "nonce-registry-2")

        trusted = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{first['source_onboarding_session_id']}/finalize?node_nonce=nonce-registry-1"
        )
        self.assertEqual(trusted.status_code, 200, trusted.text)
        self.assertEqual(trusted.json()["onboarding_status"], "approved")

        listed = self.client.get("/api/system/nodes/registry", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(listed.status_code, 200, listed.text)
        items = listed.json()["items"]
        self.assertEqual(len(items), 2)
        by_id = {item["node_id"]: item for item in items}
        self.assertEqual(by_id[first["node_id"]]["registry_state"], "trusted")
        self.assertEqual(by_id[second["node_id"]]["registry_state"], "approved")
        self.assertEqual(by_id[first["node_id"]]["declared_capabilities"], [])
        self.assertEqual(by_id[first["node_id"]]["enabled_providers"], [])
        self.assertIsNone(by_id[first["node_id"]]["capability_declaration_version"])
        self.assertIsNone(by_id[first["node_id"]]["capability_declaration_timestamp"])
        self.assertIsNone(by_id[first["node_id"]]["capability_profile_id"])

        approved_only = self.client.get(
            "/api/system/nodes/registry?state=approved",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(approved_only.status_code, 200, approved_only.text)
        self.assertEqual(len(approved_only.json()["items"]), 1)
        self.assertEqual(approved_only.json()["items"][0]["node_id"], second["node_id"])

    def test_delete_registration_removes_trust_record(self) -> None:
        started = self.client.post(
            "/api/system/nodes/onboarding/sessions",
            json={
                "node_name": "delete-node",
                "node_type": "ai-node",
                "node_software_version": "1.0.0",
                "protocol_version": "1.0",
                "node_nonce": "nonce-api-delete",
            },
        )
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]
        state = started.json()["session"]["approval_url"].split("state=", 1)[1]
        approve = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/approve?state={state}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(approve.status_code, 200, approve.text)
        node_id = approve.json()["registration"]["node_id"]

        finalized = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-api-delete"
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        self.assertEqual(finalized.json()["onboarding_status"], "approved")
        self.assertIsNotNone(self.trust_store.get_by_node(node_id))

        deleted = self.client.delete(
            f"/api/system/nodes/registrations/{node_id}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["removed_node_id"], node_id)
        self.assertTrue(bool(deleted.json()["removed_registration"]))
        self.assertTrue(bool(deleted.json()["removed_trust_record"]))

        gone = self.client.get(
            f"/api/system/nodes/registrations/{node_id}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(gone.status_code, 404, gone.text)
        trust_record = self.trust_store.get_by_node(node_id)
        self.assertIsNotNone(trust_record)
        assert trust_record is not None
        self.assertEqual(trust_record.trust_status, "revoked")
        self.assertEqual(trust_record.revocation_action, "remove")

    def test_repeated_onboarding_same_nonce_is_rejected(self) -> None:
        first = self._start_and_approve("sticky-node", "ai-node", "nonce-sticky-1")
        first_session_id = first["source_onboarding_session_id"]
        finalized = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{first_session_id}/finalize?node_nonce=nonce-sticky-1"
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        self.assertEqual(finalized.json()["onboarding_status"], "approved")
        second = self.client.post(
            "/api/system/nodes/onboarding/sessions",
            json={
                "node_name": "sticky-node-renamed",
                "node_type": "ai-node",
                "node_software_version": "1.0.0",
                "protocol_version": "1.0",
                "node_nonce": "nonce-sticky-1",
            },
        )
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(second.json()["detail"]["error"], "duplicate_node_identity")

    def test_revoke_registration_marks_revoked_and_removes_trust_record(self) -> None:
        started = self.client.post(
            "/api/system/nodes/onboarding/sessions",
            json={
                "node_name": "revoke-node",
                "node_type": "ai-node",
                "node_software_version": "1.0.0",
                "protocol_version": "1.0",
                "node_nonce": "nonce-api-revoke",
            },
        )
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]
        state = started.json()["session"]["approval_url"].split("state=", 1)[1]
        approve = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/approve?state={state}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(approve.status_code, 200, approve.text)
        node_id = approve.json()["registration"]["node_id"]

        finalized = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-api-revoke"
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        self.assertEqual(finalized.json()["onboarding_status"], "approved")
        self.assertIsNotNone(self.trust_store.get_by_node(node_id))

        revoked = self.client.post(
            f"/api/system/nodes/registrations/{node_id}/revoke",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(revoked.json()["registration"]["registry_state"], "revoked")
        self.assertTrue(bool(revoked.json()["removed_trust_record"]))
        trust_record = self.trust_store.get_by_node(node_id)
        self.assertIsNotNone(trust_record)
        assert trust_record is not None
        self.assertEqual(trust_record.trust_status, "revoked")
        self.assertEqual(trust_record.revocation_action, "revoke")


if __name__ == "__main__":
    unittest.main()

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


@unittest.skipIf(not FASTAPI_STACK_AVAILABLE, "fastapi/testclient not available in this environment")
class TestNodeRegistrationsApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sessions = NodeOnboardingSessionsStore(path=Path(self.tmpdir.name) / "node_onboarding_sessions.json")
        self.registrations = NodeRegistrationsStore(path=Path(self.tmpdir.name) / "node_registrations.json")
        self.trust_store = NodeTrustStore(path=Path(self.tmpdir.name) / "node_trust_records.json")
        self.trust_issuance = NodeTrustIssuanceService(self.trust_store)
        app = FastAPI()
        app.include_router(
            build_system_router(
                _FakeRegistry(),
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

        got = self.client.get(f"/api/system/nodes/registrations/{node_id}", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(got.status_code, 200, got.text)
        registration = got.json()["registration"]
        self.assertEqual(registration["node_type"], "ai")
        self.assertEqual(registration["requested_node_type"], "ai-node")

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
        self.assertEqual(finalized.json()["activation"]["node_type"], "ai")

        got = self.client.get(f"/api/system/nodes/registrations/{node_id}", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["registration"]["trust_status"], "trusted")

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
        self.assertIsNone(self.trust_store.get_by_node(node_id))

    def test_repeated_onboarding_same_nonce_reuses_node_id(self) -> None:
        first = self._start_and_approve("sticky-node", "ai-node", "nonce-sticky-1")
        first_session_id = first["source_onboarding_session_id"]
        finalized = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{first_session_id}/finalize?node_nonce=nonce-sticky-1"
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        self.assertEqual(finalized.json()["onboarding_status"], "approved")
        second = self._start_and_approve("sticky-node-renamed", "ai-node", "nonce-sticky-1")

        self.assertEqual(first["node_id"], second["node_id"])

        listed = self.client.get("/api/system/nodes/registrations", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(listed.status_code, 200, listed.text)
        items = listed.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["node_id"], first["node_id"])


if __name__ == "__main__":
    unittest.main()

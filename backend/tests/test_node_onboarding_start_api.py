import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.system import build_system_router
    FASTAPI_STACK_AVAILABLE = True
except Exception:  # pragma: no cover - local env may not include FastAPI deps
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
class TestNodeOnboardingStartApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = NodeOnboardingSessionsStore(path=Path(self.tmpdir.name) / "node_onboarding_sessions.json")
        self.registrations = NodeRegistrationsStore(path=Path(self.tmpdir.name) / "node_registrations.json")
        self.trust_store = NodeTrustStore(path=Path(self.tmpdir.name) / "node_trust_records.json")
        self.trust_issuance = NodeTrustIssuanceService(self.trust_store)
        app = FastAPI()
        app.include_router(
            build_system_router(
                _FakeRegistry(),
                onboarding_sessions_store=self.store,
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
                "SYNTHIA_NODE_ONBOARDING_SUPPORTED_TYPES": "ai-node",
                "SYNTHIA_ADMIN_TOKEN": "test-token",
            },
            clear=False,
        )
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.tmpdir.cleanup()

    def _payload(self) -> dict[str, str]:
        return {
            "node_name": "office-node",
            "node_type": "ai-node",
            "node_software_version": "0.1.0",
            "protocol_version": "1.0",
            "hostname": "office-node-host",
            "ui_endpoint": "http://office-node-host:8765/ui",
            "node_nonce": "nonce-abc",
        }

    def test_start_session_success(self) -> None:
        resp = self.client.post("/api/system/nodes/onboarding/sessions", json=self._payload())
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        session = body["session"]
        self.assertEqual(session["onboarding_status"], "pending_approval")
        self.assertEqual(session["node_name"], "office-node")
        self.assertEqual(session["node_type"], "ai")
        self.assertEqual(session["node_software_version"], "0.1.0")
        self.assertEqual(session["requested_node_type"], "ai-node")
        self.assertIn("session_id", session)
        self.assertIn("approval_url", session)
        self.assertIn("expires_at", session)
        self.assertEqual(session["requested_hostname"], "office-node-host")
        self.assertEqual(session["requested_ui_endpoint"], "http://office-node-host:8765/ui")
        self.assertEqual(session["finalize"]["method"], "GET")
        self.assertIn("/api/system/nodes/onboarding/sessions/", session["finalize"]["path"])
        self.assertIn("/onboarding/registrations/approve", session["approval_url"])

    def test_invalid_ui_endpoint_rejected(self) -> None:
        payload = self._payload()
        payload["ui_endpoint"] = "office-node-host/ui"
        resp = self.client.post("/api/system/nodes/onboarding/sessions", json=payload)
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["error"], "ui_endpoint_invalid")

    def test_legacy_ai_node_alias_routes_emit_deprecation_headers(self) -> None:
        started = self.client.post("/api/system/ai-nodes/onboarding/sessions", json=self._payload())
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.headers.get("Deprecation"), "true")
        self.assertEqual(started.headers.get("Sunset"), "2026-09-30")
        self.assertIn("deprecated", str(started.headers.get("Warning") or "").lower())

        session_id = started.json()["session"]["session_id"]
        approval_url = started.json()["session"]["approval_url"]
        state = approval_url.split("state=", 1)[1]
        approved = self.client.post(
            f"/api/system/ai-nodes/onboarding/sessions/{session_id}/approve?state={state}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.headers.get("Deprecation"), "true")

    def test_duplicate_active_session(self) -> None:
        first = self.client.post("/api/system/nodes/onboarding/sessions", json=self._payload())
        self.assertEqual(first.status_code, 200, first.text)

        second = self.client.post("/api/system/nodes/onboarding/sessions", json=self._payload())
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(second.json()["detail"]["error"], "duplicate_active_session")

    def test_duplicate_registered_identity_rejected(self) -> None:
        started = self.client.post("/api/system/nodes/onboarding/sessions", json=self._payload())
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]
        approval_url = started.json()["session"]["approval_url"]
        state = approval_url.split("state=", 1)[1]
        approve = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/approve?state={state}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(approve.status_code, 200, approve.text)
        self.store.consume_final_payload(session_id)

        second = self.client.post("/api/system/nodes/onboarding/sessions", json=self._payload())
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(second.json()["detail"]["error"], "duplicate_node_identity")

    def test_node_type_unsupported(self) -> None:
        payload = self._payload()
        payload["node_type"] = "not-ai-node"
        resp = self.client.post("/api/system/nodes/onboarding/sessions", json=payload)
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["error"], "node_type_unsupported")

    def test_supported_node_types_can_be_extended(self) -> None:
        payload = self._payload()
        payload["node_type"] = "sensor-node"
        with patch.dict(os.environ, {"SYNTHIA_NODE_ONBOARDING_SUPPORTED_TYPES": "ai-node,sensor-node"}, clear=False):
            resp = self.client.post("/api/system/nodes/onboarding/sessions", json=payload)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["session"]["node_type"], "sensor")
        self.assertEqual(resp.json()["session"]["requested_node_type"], "sensor-node")

    def test_email_node_is_supported_by_default(self) -> None:
        payload = self._payload()
        payload["node_type"] = "email-node"
        with patch.dict(os.environ, {"SYNTHIA_NODE_ONBOARDING_SUPPORTED_TYPES": ""}, clear=False):
            resp = self.client.post("/api/system/nodes/onboarding/sessions", json=payload)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["session"]["node_type"], "email")
        self.assertEqual(resp.json()["session"]["requested_node_type"], "email-node")

    def test_protocol_version_unsupported(self) -> None:
        payload = self._payload()
        payload["protocol_version"] = "99.9"
        resp = self.client.post("/api/system/nodes/onboarding/sessions", json=payload)
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["error"], "protocol_version_unsupported")

    def test_registration_disabled(self) -> None:
        with patch.dict(os.environ, {"SYNTHIA_AI_NODE_ONBOARDING_ENABLED": "false"}, clear=False):
            resp = self.client.post("/api/system/nodes/onboarding/sessions", json=self._payload())
        self.assertEqual(resp.status_code, 503, resp.text)
        self.assertEqual(resp.json()["detail"]["error"], "registration_disabled")

    def test_admin_can_approve_and_terminal_transition_is_enforced(self) -> None:
        started = self.client.post("/api/system/nodes/onboarding/sessions", json=self._payload())
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]
        approval_url = started.json()["session"]["approval_url"]
        state = approval_url.split("state=", 1)[1]

        approve = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/approve?state={state}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(approve.status_code, 200, approve.text)
        self.assertEqual(approve.json()["session"]["session_state"], "approved")
        self.assertEqual(approve.json()["session"]["approved_by_user_id"], "admin_token")
        self.assertIn("registration", approve.json())
        self.assertEqual(approve.json()["registration"]["node_type"], "ai")
        self.assertEqual(approve.json()["registration"]["requested_node_type"], "ai-node")
        linked_node_id = approve.json()["session"]["linked_node_id"]
        self.assertIsNotNone(self.registrations.get(linked_node_id))

        reject_after_approve = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/reject?state={state}",
            headers={"X-Admin-Token": "test-token"},
            json={"rejection_reason": "late decision"},
        )
        self.assertEqual(reject_after_approve.status_code, 409, reject_after_approve.text)

    def test_approve_reject_state_tamper_rejected(self) -> None:
        started = self.client.post("/api/system/nodes/onboarding/sessions", json=self._payload())
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]

        tampered = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/approve?state=tampered",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(tampered.status_code, 400, tampered.text)
        self.assertEqual(tampered.json()["detail"], "approval_state_mismatch")

    def test_admin_can_reject(self) -> None:
        payload = self._payload()
        payload["node_nonce"] = "nonce-xyz"
        started = self.client.post("/api/system/nodes/onboarding/sessions", json=payload)
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]
        approval_url = started.json()["session"]["approval_url"]
        state = approval_url.split("state=", 1)[1]

        reject = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/reject?state={state}",
            headers={"X-Admin-Token": "test-token"},
            json={"rejection_reason": "Unrecognized node"},
        )
        self.assertEqual(reject.status_code, 200, reject.text)
        self.assertEqual(reject.json()["session"]["session_state"], "rejected")
        self.assertEqual(reject.json()["session"]["rejection_reason"], "Unrecognized node")

    def test_finalize_outcomes(self) -> None:
        started = self.client.post("/api/system/nodes/onboarding/sessions", json=self._payload())
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]

        invalid_nonce = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=wrong"
        )
        self.assertEqual(invalid_nonce.status_code, 400, invalid_nonce.text)
        self.assertEqual(invalid_nonce.json()["detail"], "node_nonce_invalid")

        pending = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-abc"
        )
        self.assertEqual(pending.status_code, 200, pending.text)
        self.assertEqual(pending.json()["onboarding_status"], "pending")

        approval_url = started.json()["session"]["approval_url"]
        state = approval_url.split("state=", 1)[1]
        approve = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/approve?state={state}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(approve.status_code, 200, approve.text)

        approved = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-abc"
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["onboarding_status"], "approved")
        self.assertIn("activation", approved.json())
        self.assertEqual(approved.json()["activation"]["node_type"], "ai-node")

        consumed = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-abc"
        )
        self.assertEqual(consumed.status_code, 200, consumed.text)
        self.assertEqual(consumed.json()["onboarding_status"], "approved")
        self.assertTrue(consumed.json().get("replayed"))

    def test_requested_node_id_is_preserved_for_activation_payload(self) -> None:
        payload = self._payload()
        payload["node_nonce"] = "nonce-legacy-preserve"
        payload["node_id"] = "node-j2u7V_weljvD"
        started = self.client.post("/api/system/nodes/onboarding/sessions", json=payload)
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]
        state = started.json()["session"]["approval_url"].split("state=", 1)[1]

        approve = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/approve?state={state}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(approve.status_code, 200, approve.text)
        self.assertEqual(approve.json()["session"]["linked_node_id"], "node-j2u7V_weljvD")

        finalized = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-legacy-preserve"
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        self.assertEqual(finalized.json()["onboarding_status"], "approved")
        self.assertEqual(finalized.json()["activation"]["node_id"], "node-j2u7V_weljvD")

    def test_uuid_node_id_is_preserved_for_activation_payload(self) -> None:
        payload = self._payload()
        payload["node_nonce"] = "nonce-uuid-preserve"
        payload["node_id"] = "123e4567-e89b-42d3-a456-426614174000"
        started = self.client.post("/api/system/nodes/onboarding/sessions", json=payload)
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]
        state = started.json()["session"]["approval_url"].split("state=", 1)[1]

        approve = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/approve?state={state}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(approve.status_code, 200, approve.text)
        self.assertEqual(approve.json()["session"]["linked_node_id"], "123e4567-e89b-42d3-a456-426614174000")

        finalized = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-uuid-preserve"
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        self.assertEqual(finalized.json()["onboarding_status"], "approved")
        self.assertEqual(finalized.json()["activation"]["node_id"], "123e4567-e89b-42d3-a456-426614174000")

    def test_finalize_returns_invalid_for_unknown_session(self) -> None:
        resp = self.client.get("/api/system/nodes/onboarding/sessions/does-not-exist/finalize?node_nonce=nonce-abc")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["onboarding_status"], "invalid")

    def test_finalize_expired_session(self) -> None:
        started = self.client.post("/api/system/nodes/onboarding/sessions", json=self._payload())
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]
        session = self.store.get(session_id)
        session.expires_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.store.expire_stale_sessions()

        resp = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-abc"
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["onboarding_status"], "expired")


if __name__ == "__main__":
    unittest.main()

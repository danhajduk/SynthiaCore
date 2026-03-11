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
from app.system.onboarding.capability_acceptance import NodeCapabilityAcceptanceService
from app.system.onboarding.capability_profiles import NodeCapabilityProfilesStore


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
class TestNodeCapabilityDeclarationApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sessions = NodeOnboardingSessionsStore(path=Path(self.tmpdir.name) / "node_onboarding_sessions.json")
        self.registrations = NodeRegistrationsStore(path=Path(self.tmpdir.name) / "node_registrations.json")
        self.trust_store = NodeTrustStore(path=Path(self.tmpdir.name) / "node_trust_records.json")
        self.trust_issuance = NodeTrustIssuanceService(self.trust_store)
        self.capability_profiles = NodeCapabilityProfilesStore(path=Path(self.tmpdir.name) / "node_capability_profiles.json")
        self.capability_acceptance = NodeCapabilityAcceptanceService(self.capability_profiles)
        app = FastAPI()
        app.include_router(
            build_system_router(
                _FakeRegistry(),
                onboarding_sessions_store=self.sessions,
                node_registrations_store=self.registrations,
                node_trust_issuance=self.trust_issuance,
                node_capability_acceptance=self.capability_acceptance,
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

    def _trusted_node(self) -> tuple[str, str]:
        started = self.client.post(
            "/api/system/nodes/onboarding/sessions",
            json={
                "node_name": "main-ai-node",
                "node_type": "ai-node",
                "node_software_version": "0.2.0",
                "protocol_version": "1.0",
                "node_nonce": "nonce-capability-1",
            },
        )
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session"]["session_id"]
        state = started.json()["session"]["approval_url"].split("state=", 1)[1]
        approved = self.client.post(
            f"/api/system/nodes/onboarding/sessions/{session_id}/approve?state={state}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        node_id = approved.json()["registration"]["node_id"]

        finalized = self.client.get(
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-capability-1"
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        self.assertEqual(finalized.json()["onboarding_status"], "approved")

        trust = self.trust_store.get_by_node(node_id)
        self.assertIsNotNone(trust)
        assert trust is not None
        return node_id, trust.node_trust_token

    def _manifest(self, node_id: str) -> dict:
        return {
            "manifest_version": "1.0",
            "node": {
                "node_id": node_id,
                "node_type": "ai-node",
                "node_name": "main-ai-node",
                "node_software_version": "0.2.0",
            },
            "declared_task_families": ["task.classification", "task.summarization"],
            "supported_providers": ["openai", "local-llm"],
            "enabled_providers": ["openai"],
            "node_features": {
                "telemetry": True,
                "governance_refresh": True,
                "lifecycle_events": True,
                "provider_failover": False,
            },
            "environment_hints": {
                "deployment_target": "edge",
                "acceleration": "cpu",
                "network_tier": "lan",
                "region": "home",
            },
        }

    def test_accepts_capability_declaration_for_trusted_node(self) -> None:
        node_id, trust_token = self._trusted_node()
        res = self.client.post(
            "/api/system/nodes/capabilities/declaration",
            json={"manifest": self._manifest(node_id)},
            headers={"X-Node-Trust-Token": trust_token},
        )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["acceptance_status"], "accepted")
        self.assertEqual(payload["node_id"], node_id)
        self.assertEqual(payload["manifest_version"], "1.0")
        self.assertEqual(payload["declared_capabilities"], ["task.classification", "task.summarization"])
        self.assertEqual(payload["enabled_providers"], ["openai"])
        self.assertTrue(str(payload.get("capability_profile_id") or "").startswith(f"cap-{node_id}-v"))

        registration = self.registrations.get(node_id)
        self.assertIsNotNone(registration)
        assert registration is not None
        self.assertEqual(registration.declared_capabilities, ["task.classification", "task.summarization"])
        self.assertEqual(registration.enabled_providers, ["openai"])
        self.assertEqual(registration.capability_declaration_version, "1.0")
        self.assertTrue(str(registration.capability_declaration_timestamp or "").strip())
        self.assertEqual(registration.capability_profile_id, payload["capability_profile_id"])

    def test_rejects_untrusted_node_token(self) -> None:
        node_id, _trust_token = self._trusted_node()
        res = self.client.post(
            "/api/system/nodes/capabilities/declaration",
            json={"manifest": self._manifest(node_id)},
            headers={"X-Node-Trust-Token": "wrong-token"},
        )
        self.assertEqual(res.status_code, 403, res.text)
        self.assertEqual(res.json()["detail"]["error"], "untrusted_node")

    def test_rejects_invalid_schema(self) -> None:
        node_id, trust_token = self._trusted_node()
        manifest = self._manifest(node_id)
        manifest["node"]["unknown"] = "x"
        res = self.client.post(
            "/api/system/nodes/capabilities/declaration",
            json={"manifest": manifest},
            headers={"X-Node-Trust-Token": trust_token},
        )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"]["error"], "invalid_schema")

    def test_rejects_unsupported_capability_version(self) -> None:
        node_id, trust_token = self._trusted_node()
        manifest = self._manifest(node_id)
        manifest["manifest_version"] = "9.9"
        res = self.client.post(
            "/api/system/nodes/capabilities/declaration",
            json={"manifest": manifest},
            headers={"X-Node-Trust-Token": trust_token},
        )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"]["error"], "unsupported_capability_version")

    def test_rejects_unsupported_task_family_by_policy(self) -> None:
        node_id, trust_token = self._trusted_node()
        manifest = self._manifest(node_id)
        manifest["declared_task_families"] = ["task.classification", "task.unknown.future"]
        with patch.dict(os.environ, {"SYNTHIA_NODE_ALLOWED_TASK_FAMILIES": "task.classification,task.summarization"}, clear=False):
            res = self.client.post(
                "/api/system/nodes/capabilities/declaration",
                json={"manifest": manifest},
                headers={"X-Node-Trust-Token": trust_token},
            )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"]["error"], "unsupported_task_family")

    def test_rejects_unsupported_provider_identifier_by_policy(self) -> None:
        node_id, trust_token = self._trusted_node()
        manifest = self._manifest(node_id)
        manifest["supported_providers"] = ["openai", "provider-x"]
        with patch.dict(os.environ, {"SYNTHIA_NODE_ALLOWED_PROVIDERS": "openai,local-llm"}, clear=False):
            res = self.client.post(
                "/api/system/nodes/capabilities/declaration",
                json={"manifest": manifest},
                headers={"X-Node-Trust-Token": trust_token},
            )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"]["error"], "unsupported_provider_identifier")

    def test_admin_can_list_and_get_capability_profiles(self) -> None:
        node_id, trust_token = self._trusted_node()
        declared = self.client.post(
            "/api/system/nodes/capabilities/declaration",
            json={"manifest": self._manifest(node_id)},
            headers={"X-Node-Trust-Token": trust_token},
        )
        self.assertEqual(declared.status_code, 200, declared.text)
        profile_id = declared.json()["capability_profile_id"]

        listed = self.client.get(
            f"/api/system/nodes/capabilities/profiles?node_id={node_id}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        items = listed.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["profile_id"], profile_id)
        self.assertEqual(items[0]["node_id"], node_id)

        got = self.client.get(
            f"/api/system/nodes/capabilities/profiles/{profile_id}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(got.status_code, 200, got.text)
        profile = got.json()["profile"]
        self.assertEqual(profile["profile_id"], profile_id)
        self.assertEqual(profile["node_id"], node_id)
        self.assertIn("declaration_raw", profile)


if __name__ == "__main__":
    unittest.main()

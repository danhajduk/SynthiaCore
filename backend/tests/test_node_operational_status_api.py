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
from app.system.onboarding.governance import NodeGovernanceService, NodeGovernanceStore
from app.system.onboarding.governance_status import NodeGovernanceStatusService, NodeGovernanceStatusStore
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


@unittest.skipIf(not FASTAPI_STACK_AVAILABLE, "fastapi/testclient not available in this environment")
class TestNodeOperationalStatusApi(unittest.TestCase):
    def setUp(self) -> None:
        system_api._RATE_WINDOWS.clear()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sessions = NodeOnboardingSessionsStore(path=Path(self.tmpdir.name) / "node_onboarding_sessions.json")
        self.registrations = NodeRegistrationsStore(path=Path(self.tmpdir.name) / "node_registrations.json")
        self.trust_store = NodeTrustStore(path=Path(self.tmpdir.name) / "node_trust_records.json")
        self.trust_issuance = NodeTrustIssuanceService(self.trust_store)
        self.capability_profiles = NodeCapabilityProfilesStore(path=Path(self.tmpdir.name) / "node_capability_profiles.json")
        self.capability_acceptance = NodeCapabilityAcceptanceService(self.capability_profiles)
        self.governance_store = NodeGovernanceStore(path=Path(self.tmpdir.name) / "node_governance_bundles.json")
        self.governance_service = NodeGovernanceService(self.governance_store)
        self.governance_status_store = NodeGovernanceStatusStore(path=Path(self.tmpdir.name) / "node_governance_status.json")
        self.governance_status_service = NodeGovernanceStatusService(self.governance_status_store)

        app = FastAPI()
        app.include_router(
            build_system_router(
                _FakeRegistry(),
                onboarding_sessions_store=self.sessions,
                node_registrations_store=self.registrations,
                node_trust_issuance=self.trust_issuance,
                node_capability_acceptance=self.capability_acceptance,
                node_governance_service=self.governance_service,
                node_governance_status_service=self.governance_status_service,
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
                "node_nonce": "nonce-op-status-1",
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
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-op-status-1"
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        self.assertEqual(finalized.json()["onboarding_status"], "approved")

        trust = self.trust_store.get_by_node(node_id)
        self.assertIsNotNone(trust)
        assert trust is not None
        return node_id, trust.node_trust_token

    def _declare_capabilities(self, node_id: str, trust_token: str) -> None:
        manifest = {
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
        declared = self.client.post(
            "/api/system/nodes/capabilities/declaration",
            json={"manifest": manifest},
            headers={"X-Node-Trust-Token": trust_token},
        )
        self.assertEqual(declared.status_code, 200, declared.text)

    def test_admin_can_query_operational_status(self) -> None:
        node_id, trust_token = self._trusted_node()
        self._declare_capabilities(node_id, trust_token)

        res = self.client.get(
            f"/api/system/nodes/operational-status/{node_id}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["node_id"], node_id)
        self.assertEqual(payload["lifecycle_state"], "trusted")
        self.assertEqual(payload["capability_status"], "accepted")
        self.assertEqual(payload["governance_status"], "issued")
        self.assertTrue(bool(payload["operational_ready"]))
        self.assertTrue(str(payload.get("active_governance_version") or "").startswith("gov-v"))
        self.assertIn("private, max-age=15", res.headers.get("cache-control", ""))

    def test_node_can_query_operational_status_with_trust_token(self) -> None:
        node_id, trust_token = self._trusted_node()
        self._declare_capabilities(node_id, trust_token)

        res = self.client.get(
            f"/api/system/nodes/operational-status/{node_id}",
            headers={"X-Node-Trust-Token": trust_token},
        )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["node_id"], node_id)
        self.assertEqual(payload["governance_status"], "issued")

    def test_rejects_invalid_node_token(self) -> None:
        node_id, _trust_token = self._trusted_node()
        res = self.client.get(
            f"/api/system/nodes/operational-status/{node_id}",
            headers={"X-Node-Trust-Token": "wrong-token"},
        )
        self.assertEqual(res.status_code, 403, res.text)
        self.assertEqual(res.json()["detail"]["error"], "untrusted_node")


if __name__ == "__main__":
    unittest.main()

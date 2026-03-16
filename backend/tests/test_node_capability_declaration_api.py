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

from app.system.onboarding import (
    ModelRoutingRegistryService,
    ModelRoutingRegistryStore,
    NodeOnboardingSessionsStore,
    NodeRegistrationsStore,
    NodeTrustIssuanceService,
    NodeTrustStore,
)
from app.system.onboarding.capability_acceptance import NodeCapabilityAcceptanceService
from app.system.onboarding.capability_profiles import NodeCapabilityProfilesStore
from app.system.onboarding.governance import NodeGovernanceService, NodeGovernanceStore
from app.system.onboarding.governance_status import NodeGovernanceStatusService, NodeGovernanceStatusStore
from app.system.onboarding.provider_model_policy import ProviderModelApprovalPolicyService, ProviderModelPolicyStore
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
class TestNodeCapabilityDeclarationApi(unittest.TestCase):
    def setUp(self) -> None:
        system_api._RATE_WINDOWS.clear()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sessions = NodeOnboardingSessionsStore(path=Path(self.tmpdir.name) / "node_onboarding_sessions.json")
        self.registrations = NodeRegistrationsStore(path=Path(self.tmpdir.name) / "node_registrations.json")
        self.trust_store = NodeTrustStore(path=Path(self.tmpdir.name) / "node_trust_records.json")
        self.trust_issuance = NodeTrustIssuanceService(self.trust_store)
        self.capability_profiles = NodeCapabilityProfilesStore(path=Path(self.tmpdir.name) / "node_capability_profiles.json")
        self.provider_policy_store = ProviderModelPolicyStore(path=Path(self.tmpdir.name) / "provider_model_policy.json")
        self.provider_policy_service = ProviderModelApprovalPolicyService(self.provider_policy_store)
        self.routing_registry_store = ModelRoutingRegistryStore(path=Path(self.tmpdir.name) / "model_routing_registry.json")
        self.routing_registry_service = ModelRoutingRegistryService(self.routing_registry_store)
        self.capability_acceptance = NodeCapabilityAcceptanceService(
            self.capability_profiles,
            provider_model_policy=self.provider_policy_service,
        )
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
                provider_model_policy_service=self.provider_policy_service,
                model_routing_registry_service=self.routing_registry_service,
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
            "provider_intelligence": [
                {
                    "provider": "openai",
                    "available_models": [
                        {
                            "model_id": "gpt-4o-mini",
                            "pricing": {"input_per_1k": 0.00015, "output_per_1k": 0.0006},
                            "latency_metrics": {"p50_ms": 120.0, "p95_ms": 280.0},
                        }
                    ],
                }
            ],
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
        self.assertEqual(payload["provider_intelligence"][0]["provider"], "openai")
        self.assertEqual(payload["provider_intelligence"][0]["available_models"][0]["model_id"], "gpt-4o-mini")
        self.assertEqual(payload["provider_intelligence"][0]["available_models"][0]["normalized_model_id"], "gpt-4o-mini")
        self.assertEqual(payload["unified_model_descriptors"][0]["normalized_model_id"], "gpt-4o-mini")
        self.assertTrue(str(payload.get("capability_profile_id") or "").startswith(f"cap-{node_id}-v"))
        self.assertEqual(payload["capability_taxonomy"]["activation"]["stage"], "operational")
        self.assertEqual(payload["capability_taxonomy"]["categories"][0]["category_id"], "task_families")
        self.assertTrue(str(payload.get("governance_version") or "").startswith("gov-v"))
        self.assertTrue(str(payload.get("governance_issued_at") or "").strip())

        registration = self.registrations.get(node_id)
        self.assertIsNotNone(registration)
        assert registration is not None
        self.assertEqual(registration.declared_capabilities, ["task.classification", "task.summarization"])
        self.assertEqual(registration.enabled_providers, ["openai"])
        self.assertEqual(registration.provider_intelligence[0]["provider"], "openai")
        self.assertEqual(registration.capability_declaration_version, "1.0")
        self.assertTrue(str(registration.capability_declaration_timestamp or "").strip())
        self.assertEqual(registration.capability_profile_id, payload["capability_profile_id"])
        governance_items = self.governance_store.list(node_id=node_id)
        self.assertEqual(len(governance_items), 1)
        self.assertEqual(governance_items[0].governance_version, payload["governance_version"])
        status = self.governance_status_store.get(node_id)
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status.active_governance_version, payload["governance_version"])
        self.assertTrue(str(status.last_issued_timestamp or "").strip())
        routing = self.client.get(
            f"/api/system/nodes/providers/routing-metadata?node_id={node_id}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(routing.status_code, 200, routing.text)
        routing_items = routing.json()["items"]
        self.assertEqual(len(routing_items), 1)
        self.assertEqual(routing_items[0]["provider"], "openai")
        self.assertEqual(routing_items[0]["normalized_model_id"], "gpt-4o-mini")
        self.assertTrue(routing_items[0]["node_available"])

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

    def test_accepts_provider_identifier_from_node_when_allowlist_not_configured(self) -> None:
        node_id, trust_token = self._trusted_node()
        manifest = self._manifest(node_id)
        manifest["supported_providers"] = ["provider-x"]
        manifest["enabled_providers"] = ["provider-x"]
        manifest["provider_intelligence"] = [
            {"provider": "provider-x", "available_models": [{"model_id": "x-large", "pricing": {"input_per_1k": 0.1}}]}
        ]
        with patch.dict(os.environ, {"SYNTHIA_NODE_ALLOWED_PROVIDERS": ""}, clear=False):
            res = self.client.post(
                "/api/system/nodes/capabilities/declaration",
                json={"manifest": manifest},
                headers={"X-Node-Trust-Token": trust_token},
            )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["enabled_providers"], ["provider-x"])
        self.assertEqual(res.json()["provider_intelligence"][0]["provider"], "provider-x")

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
        self.assertEqual(items[0]["provider_intelligence"][0]["provider"], "openai")

    def test_provider_model_policy_can_reject_unapproved_models(self) -> None:
        node_id, trust_token = self._trusted_node()
        set_policy = self.client.put(
            "/api/system/nodes/providers/model-policy/openai",
            json={"allowed_models": ["gpt-4.1-mini"]},
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(set_policy.status_code, 200, set_policy.text)
        self.assertEqual(set_policy.json()["policy"]["provider"], "openai")
        self.assertEqual(set_policy.json()["policy"]["allowed_models"], ["gpt-4.1-mini"])

        listed = self.client.get(
            "/api/system/nodes/providers/model-policy",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()["items"]), 1)

        rejected = self.client.post(
            "/api/system/nodes/capabilities/declaration",
            json={"manifest": self._manifest(node_id)},
            headers={"X-Node-Trust-Token": trust_token},
        )
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertEqual(rejected.json()["detail"]["error"], "provider_model_not_approved")

    def test_trusted_node_can_submit_provider_capability_report(self) -> None:
        node_id, trust_token = self._trusted_node()
        report = self.client.post(
            "/api/system/nodes/providers/capabilities/report",
            json={
                "node_id": node_id,
                "provider_intelligence": [
                    {
                        "provider": "OpenAI",
                        "available_models": [
                            {
                                "model_id": " GPT-4O-Mini ",
                                "pricing": {"input_per_1k": 0.00015},
                                "latency_metrics": {"p50_ms": 120.0},
                            }
                        ],
                    }
                ],
                "node_available": True,
            },
            headers={"X-Node-Trust-Token": trust_token},
        )
        self.assertEqual(report.status_code, 200, report.text)
        payload = report.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["node_id"], node_id)
        self.assertEqual(payload["provider_intelligence"][0]["provider"], "openai")
        self.assertEqual(
            payload["provider_intelligence"][0]["available_models"][0]["normalized_model_id"],
            "gpt-4o-mini",
        )
        self.assertEqual(payload["unified_model_descriptors"][0]["normalized_model_id"], "gpt-4o-mini")

        registration = self.registrations.get(node_id)
        self.assertIsNotNone(registration)
        assert registration is not None
        self.assertEqual(registration.provider_intelligence[0]["provider"], "openai")
        routing = self.client.get(
            f"/api/system/nodes/providers/routing-metadata?node_id={node_id}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(routing.status_code, 200, routing.text)
        self.assertEqual(len(routing.json()["items"]), 1)
        self.assertTrue(routing.json()["items"][0]["node_available"])

        report_offline = self.client.post(
            "/api/system/nodes/providers/capabilities/report",
            json={"node_id": node_id, "provider_intelligence": payload["provider_intelligence"], "node_available": False},
            headers={"X-Node-Trust-Token": trust_token},
        )
        self.assertEqual(report_offline.status_code, 200, report_offline.text)
        routing_after = self.client.get(
            f"/api/system/nodes/providers/routing-metadata?node_id={node_id}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(routing_after.status_code, 200, routing_after.text)
        self.assertFalse(routing_after.json()["items"][0]["node_available"])
        self.assertEqual(routing_after.json()["items"][0]["source"], "provider_capability_report")

    def test_provider_capability_report_rejects_untrusted_token(self) -> None:
        node_id, _trust_token = self._trusted_node()
        report = self.client.post(
            "/api/system/nodes/providers/capabilities/report",
            json={"node_id": node_id, "provider_intelligence": []},
            headers={"X-Node-Trust-Token": "wrong-token"},
        )
        self.assertEqual(report.status_code, 403, report.text)
        self.assertEqual(report.json()["detail"]["error"], "untrusted_node")

    def test_provider_capability_report_rejects_invalid_schema(self) -> None:
        node_id, trust_token = self._trusted_node()
        report = self.client.post(
            "/api/system/nodes/providers/capabilities/report",
            json={
                "node_id": node_id,
                "provider_intelligence": [{"provider": "bad provider", "available_models": []}],
            },
            headers={"X-Node-Trust-Token": trust_token},
        )
        self.assertEqual(report.status_code, 400, report.text)
        self.assertEqual(report.json()["detail"]["error"], "invalid_provider_id")


if __name__ == "__main__":
    unittest.main()

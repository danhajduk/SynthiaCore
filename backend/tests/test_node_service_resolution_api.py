import asyncio
import json
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
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None
    build_system_router = None
    FASTAPI_STACK_AVAILABLE = False

from app.system.onboarding import (
    ModelRoutingRegistryService,
    ModelRoutingRegistryStore,
    NodeBudgetService,
    NodeBudgetStore,
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
from app.system.services import ServiceCatalogStore
from app.system.auth import ServiceTokenKeyStore
from app.api import system as system_api
from app.system.audit import AuditLogStore


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


class _FakeSettingsStore:
    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    async def get(self, key: str):
        return self._data.get(key)

    async def set(self, key: str, value):
        self._data[key] = value
        return value


@unittest.skipIf(not FASTAPI_STACK_AVAILABLE, "fastapi/testclient not available in this environment")
class TestNodeServiceResolutionApi(unittest.TestCase):
    def setUp(self) -> None:
        system_api._RATE_WINDOWS.clear()
        self.tmpdir = tempfile.TemporaryDirectory()
        base = Path(self.tmpdir.name)
        self.sessions = NodeOnboardingSessionsStore(path=base / "node_onboarding_sessions.json")
        self.registrations = NodeRegistrationsStore(path=base / "node_registrations.json")
        self.trust_store = NodeTrustStore(path=base / "node_trust_records.json")
        self.trust_issuance = NodeTrustIssuanceService(self.trust_store)
        self.capability_profiles = NodeCapabilityProfilesStore(path=base / "node_capability_profiles.json")
        self.provider_policy_store = ProviderModelPolicyStore(path=base / "provider_model_policy.json")
        self.provider_policy = ProviderModelApprovalPolicyService(self.provider_policy_store)
        self.capability_acceptance = NodeCapabilityAcceptanceService(
            self.capability_profiles,
            provider_model_policy=self.provider_policy,
        )
        self.routing_store = ModelRoutingRegistryStore(path=base / "model_routing_registry.json")
        self.routing_service = ModelRoutingRegistryService(self.routing_store)
        self.budget_store = NodeBudgetStore(path=base / "node_budgets.json")
        self.budget_service = NodeBudgetService(self.budget_store, self.routing_service)
        self.governance_store = NodeGovernanceStore(path=base / "node_governance_bundles.json")
        self.governance_service = NodeGovernanceService(
            self.governance_store,
            provider_model_policy=self.provider_policy,
            node_budget_service=self.budget_service,
        )
        self.governance_status_store = NodeGovernanceStatusStore(path=base / "node_governance_status.json")
        self.governance_status_service = NodeGovernanceStatusService(self.governance_status_store)
        self.settings = _FakeSettingsStore()
        self.service_token_keys = ServiceTokenKeyStore(self.settings)
        self.service_catalog_store = ServiceCatalogStore(str(base / "service_catalogs.json"))
        self.audit_store = AuditLogStore(str(base / "audit.log"))
        self.audit_path = base / "audit.log"

        app = FastAPI()
        app.include_router(
            build_system_router(
                _FakeRegistry(),
                service_token_key_store=self.service_token_keys,
                service_catalog_store=self.service_catalog_store,
                onboarding_sessions_store=self.sessions,
                node_registrations_store=self.registrations,
                node_trust_issuance=self.trust_issuance,
                node_capability_acceptance=self.capability_acceptance,
                node_governance_service=self.governance_service,
                node_governance_status_service=self.governance_status_service,
                node_budget_service=self.budget_service,
                provider_model_policy_service=self.provider_policy,
                model_routing_registry_service=self.routing_service,
                audit_store=self.audit_store,
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

    def _audit_events(self) -> list[dict]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _trusted_node(self) -> tuple[str, str]:
        started = self.client.post(
            "/api/system/nodes/onboarding/sessions",
            json={
                "node_name": "main-ai-node",
                "node_type": "ai-node",
                "node_software_version": "0.2.0",
                "protocol_version": "1.0",
                "node_nonce": "nonce-service-resolution-1",
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
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-service-resolution-1"
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        trust = self.trust_store.get_by_node(node_id)
        self.assertIsNotNone(trust)
        assert trust is not None
        return node_id, trust.node_trust_token

    def _manifest(
        self,
        node_id: str,
        *,
        task_families: list[str] | None = None,
        enabled_providers: list[str] | None = None,
        provider_intelligence: list[dict] | None = None,
    ) -> dict:
        return {
            "manifest_version": "1.0",
            "node": {
                "node_id": node_id,
                "node_type": "ai-node",
                "node_name": "main-ai-node",
                "node_software_version": "0.2.0",
            },
            "declared_task_families": list(task_families or ["task.summarization"]),
            "supported_providers": list(enabled_providers or ["openai"]),
            "enabled_providers": list(enabled_providers or ["openai"]),
            "provider_intelligence": list(
                provider_intelligence
                or [
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
                ]
            ),
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

    def _configure_node_for_resolution(self) -> tuple[str, str]:
        node_id, trust_token = self._trusted_node()
        self.provider_policy.set_allowlist(provider="openai", allowed_models=["gpt-4o-mini"], updated_by="test")
        declared = self.client.post(
            "/api/system/nodes/capabilities/declaration",
            json={"manifest": self._manifest(node_id)},
            headers={"X-Node-Trust-Token": trust_token},
        )
        self.assertEqual(declared.status_code, 200, declared.text)
        budget_declared = self.client.post(
            "/api/system/nodes/budgets/declaration",
            headers={"X-Node-Trust-Token": trust_token},
            json={"node_id": node_id, "compute_unit": "tokens", "supports_provider_allocations": True, "supported_providers": ["openai"]},
        )
        self.assertEqual(budget_declared.status_code, 200, budget_declared.text)
        configured = self.client.put(
            f"/api/system/nodes/budgets/{node_id}",
            headers={"X-Admin-Token": "test-token"},
            json={"node_budget": {"node_money_limit": 10.0, "node_compute_limit": 10000.0, "compute_unit": "tokens"}},
        )
        self.assertEqual(configured.status_code, 200, configured.text)
        asyncio.run(
            self.service_catalog_store.upsert_service(
                service_type="ai-inference",
                service_id="summary-service",
                addon_id="summary-addon",
                endpoint="http://127.0.0.1:9100",
                health="healthy",
                capabilities=["task.summarization"],
                provider="openai",
                models=[{"model_id": "gpt-4o-mini"}],
                declared_capacity={"limits": {"max_tokens": 1000000}},
                auth_modes=["service_token"],
                required_scopes=["service.execute:task.summarization"],
                addon_registry={"addon_id": "summary-addon", "name": "Summary Addon", "version": "1.0.0", "enabled": True},
            )
        )
        return node_id, trust_token

    def test_node_can_resolve_authorize_and_report_usage_for_service(self) -> None:
        node_id, trust_token = self._configure_node_for_resolution()
        resolved = self.client.post(
            "/api/system/nodes/services/resolve",
            headers={"X-Node-Trust-Token": trust_token},
            json={
                "node_id": node_id,
                "task_family": "task.summarization",
                "task_context": {"content_type": "email"},
                "preferred_provider": "openai",
                "preferred_model": "gpt-4o-mini",
            },
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)
        payload = resolved.json()
        self.assertEqual(payload["selected_service_id"], "summary-service")
        self.assertEqual(len(payload["candidates"]), 1)
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["provider_node_id"], node_id)
        self.assertEqual(candidate["provider"], "openai")
        self.assertEqual(candidate["models_allowed"], ["gpt-4o-mini"])
        self.assertTrue(bool(candidate["budget_view"]["admissible"]))
        self.assertEqual(candidate["budget_view"]["budget_node_id"], node_id)
        self.assertEqual(candidate["budget_view"]["grant_scope_kind"], "node")

        authorized = self.client.post(
            "/api/system/nodes/services/authorize",
            headers={"X-Node-Trust-Token": trust_token},
            json={
                "node_id": node_id,
                "task_family": "task.summarization",
                "task_context": {"content_type": "email"},
                "service_id": "summary-service",
                "provider": "openai",
                "model_id": "gpt-4o-mini",
            },
        )
        self.assertEqual(authorized.status_code, 200, authorized.text)
        auth_payload = authorized.json()
        self.assertEqual(auth_payload["service_id"], "summary-service")
        self.assertEqual(auth_payload["provider"], "openai")
        self.assertTrue(str(auth_payload["token"]).strip())
        self.assertEqual(auth_payload["claims"]["aud"], "summary-service")
        self.assertEqual(auth_payload["claims"]["sub"], node_id)
        self.assertEqual(auth_payload["grant_id"], candidate["grant_id"])

        usage_report = self.client.post(
            "/api/system/nodes/budgets/usage-summary",
            headers={"X-Node-Trust-Token": trust_token},
            json={
                "node_id": node_id,
                "service": "ai.inference",
                "grant_id": auth_payload["grant_id"],
                "provider": "openai",
                "model_id": "gpt-4o-mini",
                "task_family": "task.summarization",
                "used_requests": 4,
                "used_tokens": 2000,
                "used_cost_cents": 15,
                "denials": 1,
                "error_counts": {"budget_exceeded": 1},
            },
        )
        self.assertEqual(usage_report.status_code, 200, usage_report.text)

        reports = self.client.get(
            f"/api/system/nodes/budgets/{node_id}/usage-reports?provider=openai&task_family=task.summarization",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(reports.status_code, 200, reports.text)
        self.assertEqual(len(reports.json()["items"]), 1)
        self.assertEqual(reports.json()["rollups"]["providers"][0]["provider"], "openai")
        self.assertEqual(reports.json()["rollups"]["task_families"][0]["task_family"], "task.summarization")
        resolve_events = [item for item in self._audit_events() if item.get("event_type") == "node_service_resolved"]
        self.assertGreaterEqual(len(resolve_events), 1)
        event = resolve_events[-1]
        self.assertEqual(event["actor_id"], node_id)
        self.assertEqual(event["details"]["selected_service_id"], "summary-service")
        self.assertEqual(event["details"]["candidate_count"], 1)
        self.assertEqual(event["details"]["result"], "resolved")

    def test_resolution_uses_provider_node_budget_for_delegating_node(self) -> None:
        provider_node_id, _provider_trust_token = self._configure_node_for_resolution()
        delegator_node_id, delegator_trust_token = self._trusted_node()
        declared = self.client.post(
            "/api/system/nodes/capabilities/declaration",
            json={"manifest": self._manifest(delegator_node_id, task_families=["task.summarization"], provider_intelligence=[])},
            headers={"X-Node-Trust-Token": delegator_trust_token},
        )
        self.assertEqual(declared.status_code, 200, declared.text)

        resolved = self.client.post(
            "/api/system/nodes/services/resolve",
            headers={"X-Node-Trust-Token": delegator_trust_token},
            json={
                "node_id": delegator_node_id,
                "task_family": "task.summarization",
                "preferred_provider": "openai",
                "preferred_model": "gpt-4o-mini",
            },
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)
        payload = resolved.json()
        self.assertEqual(payload["selected_service_id"], "summary-service")
        self.assertEqual(len(payload["candidates"]), 1)
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["provider_node_id"], provider_node_id)
        self.assertEqual(candidate["budget_view"]["budget_node_id"], provider_node_id)
        self.assertTrue(bool(candidate["budget_view"]["admissible"]))

        authorized = self.client.post(
            "/api/system/nodes/services/authorize",
            headers={"X-Node-Trust-Token": delegator_trust_token},
            json={
                "node_id": delegator_node_id,
                "task_family": "task.summarization",
                "service_id": "summary-service",
                "provider": "openai",
                "model_id": "gpt-4o-mini",
            },
        )
        self.assertEqual(authorized.status_code, 200, authorized.text)
        auth_payload = authorized.json()
        self.assertEqual(auth_payload["grant_id"], candidate["grant_id"])
        self.assertEqual(auth_payload["resolution"]["provider_node_id"], provider_node_id)

        usage_report = self.client.post(
            "/api/system/nodes/budgets/usage-summary",
            headers={"X-Node-Trust-Token": delegator_trust_token},
            json={
                "node_id": delegator_node_id,
                "service": "ai.inference",
                "grant_id": auth_payload["grant_id"],
                "provider": "openai",
                "model_id": "gpt-4o-mini",
                "task_family": "task.summarization",
                "used_requests": 1,
                "used_tokens": 100,
                "used_cost_cents": 2,
            },
        )
        self.assertEqual(usage_report.status_code, 200, usage_report.text)
        self.assertEqual(usage_report.json()["report"]["node_id"], provider_node_id)
        self.assertEqual(
            usage_report.json()["report"]["metadata"]["reported_by_node_id"],
            delegator_node_id,
        )

    def test_resolution_and_authorization_accept_top_level_type(self) -> None:
        node_id, trust_token = self._configure_node_for_resolution()
        resolved = self.client.post(
            "/api/system/nodes/services/resolve",
            headers={"X-Node-Trust-Token": trust_token},
            json={
                "node_id": node_id,
                "task_family": "task.summarization",
                "type": "email",
                "preferred_provider": "openai",
                "preferred_model": "gpt-4o-mini",
            },
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)
        payload = resolved.json()
        self.assertEqual(payload["task_context"]["type"], "email")
        self.assertEqual(payload["selected_service_id"], "summary-service")

        authorized = self.client.post(
            "/api/system/nodes/services/authorize",
            headers={"X-Node-Trust-Token": trust_token},
            json={
                "node_id": node_id,
                "task_family": "task.summarization",
                "type": "email",
                "service_id": "summary-service",
                "provider": "openai",
                "model_id": "gpt-4o-mini",
            },
        )
        self.assertEqual(authorized.status_code, 200, authorized.text)
        auth_payload = authorized.json()
        self.assertEqual(auth_payload["resolution"]["budget_view"]["grant_scope_kind"], "node")

    def test_resolution_rejects_conflicting_top_level_type_and_context_type(self) -> None:
        node_id, trust_token = self._configure_node_for_resolution()
        resolved = self.client.post(
            "/api/system/nodes/services/resolve",
            headers={"X-Node-Trust-Token": trust_token},
            json={
                "node_id": node_id,
                "task_family": "task.summarization",
                "type": "email",
                "task_context": {"type": "ai"},
            },
        )
        self.assertEqual(resolved.status_code, 422, resolved.text)
        self.assertIn("task_type_conflict", resolved.text)

    def test_resolution_rejects_context_encoded_task_family(self) -> None:
        node_id, trust_token = self._configure_node_for_resolution()
        resolved = self.client.post(
            "/api/system/nodes/services/resolve",
            headers={"X-Node-Trust-Token": trust_token},
            json={
                "node_id": node_id,
                "task_family": "task.summarization.email",
                "task_context": {"content_type": "email"},
            },
        )
        self.assertEqual(resolved.status_code, 422, resolved.text)
        self.assertIn("task_family_context_suffix_not_allowed", resolved.text)

    def test_resolution_rejects_type_encoded_task_family(self) -> None:
        node_id, trust_token = self._configure_node_for_resolution()
        resolved = self.client.post(
            "/api/system/nodes/services/resolve",
            headers={"X-Node-Trust-Token": trust_token},
            json={
                "node_id": node_id,
                "task_family": "task.summarization.email",
                "type": "email",
            },
        )
        self.assertEqual(resolved.status_code, 422, resolved.text)
        self.assertIn("task_family_type_suffix_not_allowed", resolved.text)

    def test_resolution_returns_no_candidates_without_configured_budget(self) -> None:
        node_id, trust_token = self._trusted_node()
        declared = self.client.post(
            "/api/system/nodes/capabilities/declaration",
            json={"manifest": self._manifest(node_id)},
            headers={"X-Node-Trust-Token": trust_token},
        )
        self.assertEqual(declared.status_code, 200, declared.text)
        asyncio.run(
            self.service_catalog_store.upsert_service(
                service_type="ai-inference",
                service_id="summary-service",
                addon_id="summary-addon",
                endpoint="http://127.0.0.1:9100",
                health="healthy",
                capabilities=["task.summarization"],
                provider="openai",
                models=[{"model_id": "gpt-4o-mini"}],
                addon_registry={"addon_id": "summary-addon", "name": "Summary Addon", "version": "1.0.0", "enabled": True},
            )
        )
        resolved = self.client.post(
            "/api/system/nodes/services/resolve",
            headers={"X-Node-Trust-Token": trust_token},
            json={"node_id": node_id, "task_family": "task.summarization"},
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()["candidates"], [])
        resolve_events = [item for item in self._audit_events() if item.get("event_type") == "node_service_resolved"]
        self.assertGreaterEqual(len(resolve_events), 1)
        event = resolve_events[-1]
        self.assertEqual(event["actor_id"], node_id)
        self.assertEqual(event["details"]["candidate_count"], 0)
        self.assertEqual(event["details"]["result"], "no_candidates")

    def test_resolution_filters_unauthorized_provider_requests(self) -> None:
        node_id, trust_token = self._configure_node_for_resolution()
        resolved = self.client.post(
            "/api/system/nodes/services/resolve",
            headers={"X-Node-Trust-Token": trust_token},
            json={
                "node_id": node_id,
                "task_family": "task.summarization",
                "preferred_provider": "anthropic",
            },
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()["candidates"], [])

    def test_outdated_node_cannot_receive_new_service_contracts_until_refresh(self) -> None:
        node_id, trust_token = self._configure_node_for_resolution()
        status = self.governance_status_store.get(node_id)
        self.assertIsNotNone(status)
        assert status is not None
        outdated_at = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        self.governance_status_store.upsert(
            node_id=node_id,
            active_governance_version=status.active_governance_version,
            last_issued_timestamp=status.last_issued_timestamp,
            last_refresh_request_timestamp=outdated_at,
        )

        blocked = self.client.post(
            "/api/system/nodes/services/resolve",
            headers={"X-Node-Trust-Token": trust_token},
            json={"node_id": node_id, "task_family": "task.summarization"},
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()["detail"]["error"], "node_governance_outdated")

        refreshed = self.client.post(
            "/api/system/nodes/governance/refresh",
            headers={"X-Node-Trust-Token": trust_token},
            json={"node_id": node_id},
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.text)

        resolved = self.client.post(
            "/api/system/nodes/services/resolve",
            headers={"X-Node-Trust-Token": trust_token},
            json={"node_id": node_id, "task_family": "task.summarization"},
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertGreaterEqual(len(resolved.json()["candidates"]), 1)


if __name__ == "__main__":
    unittest.main()

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
    NodeBudgetService,
    NodeBudgetStore,
    NodeOnboardingSessionsStore,
    NodeRegistrationsStore,
    NodeTrustIssuanceService,
    NodeTrustStore,
)
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
class TestNodeBudgetApi(unittest.TestCase):
    def setUp(self) -> None:
        system_api._RATE_WINDOWS.clear()
        self.tmpdir = tempfile.TemporaryDirectory()
        base = Path(self.tmpdir.name)
        self.sessions = NodeOnboardingSessionsStore(path=base / "node_onboarding_sessions.json")
        self.registrations = NodeRegistrationsStore(path=base / "node_registrations.json")
        self.trust_store = NodeTrustStore(path=base / "node_trust_records.json")
        self.trust_issuance = NodeTrustIssuanceService(self.trust_store)
        self.budget_store = NodeBudgetStore(path=base / "node_budgets.json")
        self.budget_service = NodeBudgetService(self.budget_store)

        app = FastAPI()
        app.include_router(
            build_system_router(
                _FakeRegistry(),
                onboarding_sessions_store=self.sessions,
                node_registrations_store=self.registrations,
                node_trust_issuance=self.trust_issuance,
                node_budget_service=self.budget_service,
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
                "node_name": "budget-node",
                "node_type": "ai-node",
                "node_software_version": "0.3.0",
                "protocol_version": "1.0",
                "node_nonce": "nonce-budget-1",
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
            f"/api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=nonce-budget-1"
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        trust = self.trust_store.get_by_node(node_id)
        self.assertIsNotNone(trust)
        assert trust is not None
        return node_id, trust.node_trust_token

    def test_trusted_node_can_declare_budget_capabilities(self) -> None:
        node_id, trust_token = self._trusted_node()
        res = self.client.post(
            "/api/system/nodes/budgets/declaration",
            headers={"X-Node-Trust-Token": trust_token},
            json={
                "node_id": node_id,
                "currency": "USD",
                "compute_unit": "cost_units",
                "default_period": "monthly",
                "supports_money_budget": True,
                "supports_compute_budget": True,
                "supports_customer_allocations": True,
                "supports_provider_allocations": True,
                "supported_providers": ["openai", "local-llm"],
                "setup_requirements": ["operator_budget_confirmation"],
                "suggested_money_limit": 10.0,
                "suggested_compute_limit": 100.0,
            },
        )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()["declaration"]
        self.assertEqual(payload["node_id"], node_id)
        self.assertTrue(payload["supports_provider_allocations"])
        self.assertEqual(payload["supported_providers"], ["local-llm", "openai"])

    def test_admin_can_configure_node_budget_bundle(self) -> None:
        node_id, trust_token = self._trusted_node()
        declared = self.client.post(
            "/api/system/nodes/budgets/declaration",
            headers={"X-Node-Trust-Token": trust_token},
            json={
                "node_id": node_id,
                "supports_provider_allocations": True,
                "supported_providers": ["openai"],
                "suggested_money_limit": 10.0,
                "suggested_compute_limit": 100.0,
            },
        )
        self.assertEqual(declared.status_code, 200, declared.text)

        configured = self.client.put(
            f"/api/system/nodes/budgets/{node_id}",
            headers={"X-Admin-Token": "test-token"},
            json={
                "node_budget": {
                    "currency": "USD",
                    "compute_unit": "cost_units",
                    "period": "monthly",
                    "reset_policy": "calendar",
                    "enforcement_mode": "hard_stop",
                    "overcommit_enabled": False,
                    "node_money_limit": 10.0,
                    "node_compute_limit": 100.0,
                },
                "customer_allocations": [
                    {"subject_id": "cust-a", "money_limit": 3.3, "compute_limit": 30},
                    {"subject_id": "cust-b", "money_limit": 3.3, "compute_limit": 30},
                    {"subject_id": "cust-c", "money_limit": 3.3, "compute_limit": 30},
                ],
                "provider_allocations": [
                    {"subject_id": "openai", "money_limit": 8.0, "compute_limit": 80},
                ],
            },
        )
        self.assertEqual(configured.status_code, 200, configured.text)
        budget = configured.json()["budget"]
        self.assertEqual(budget["setup_status"], "configured")
        self.assertEqual(len(budget["customer_allocations"]), 3)
        self.assertEqual(len(budget["provider_allocations"]), 1)

        listed = self.client.get("/api/system/nodes/budgets", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"][0]["node_id"], node_id)

    def test_rejects_customer_budget_sum_above_node_total_without_overcommit(self) -> None:
        node_id, trust_token = self._trusted_node()
        declared = self.client.post(
            "/api/system/nodes/budgets/declaration",
            headers={"X-Node-Trust-Token": trust_token},
            json={"node_id": node_id},
        )
        self.assertEqual(declared.status_code, 200, declared.text)

        configured = self.client.put(
            f"/api/system/nodes/budgets/{node_id}",
            headers={"X-Admin-Token": "test-token"},
            json={
                "node_budget": {
                    "node_money_limit": 10.0,
                    "node_compute_limit": 100.0,
                },
                "customer_allocations": [
                    {"subject_id": "cust-a", "money_limit": 6.0, "compute_limit": 30},
                    {"subject_id": "cust-b", "money_limit": 5.0, "compute_limit": 30},
                ],
            },
        )
        self.assertEqual(configured.status_code, 400, configured.text)
        self.assertEqual(configured.json()["detail"]["error"], "customer_budget_allocations_exceed_node_money_limit")

    def test_rejects_provider_allocation_for_unsupported_provider(self) -> None:
        node_id, trust_token = self._trusted_node()
        declared = self.client.post(
            "/api/system/nodes/budgets/declaration",
            headers={"X-Node-Trust-Token": trust_token},
            json={
                "node_id": node_id,
                "supports_provider_allocations": True,
                "supported_providers": ["openai"],
            },
        )
        self.assertEqual(declared.status_code, 200, declared.text)

        configured = self.client.put(
            f"/api/system/nodes/budgets/{node_id}",
            headers={"X-Admin-Token": "test-token"},
            json={
                "node_budget": {"node_money_limit": 10.0, "node_compute_limit": 100.0},
                "provider_allocations": [{"subject_id": "anthropic", "money_limit": 5.0, "compute_limit": 50}],
            },
        )
        self.assertEqual(configured.status_code, 400, configured.text)
        self.assertEqual(configured.json()["detail"]["error"], "provider_budget_subject_not_supported")


if __name__ == "__main__":
    unittest.main()

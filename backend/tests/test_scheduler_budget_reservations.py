import tempfile
import unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.system.audit import AuditLogStore
from app.system.onboarding import ModelRoutingRegistryService, ModelRoutingRegistryStore, NodeBudgetService, NodeBudgetStore
from app.system.scheduler.engine import SchedulerEngine
from app.system.scheduler.router import build_scheduler_router
from app.system.scheduler.store import SchedulerStore


class TestSchedulerBudgetReservations(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        base = Path(self.tmpdir.name)
        self.budget_store = NodeBudgetStore(path=base / "node_budgets.json")
        self.routing_store = ModelRoutingRegistryStore(path=base / "model_routing_registry.json")
        self.routing_service = ModelRoutingRegistryService(self.routing_store)
        self.budget_service = NodeBudgetService(self.budget_store, self.routing_service)
        self.audit_path = base / "audit.log"
        self.audit_store = AuditLogStore(str(self.audit_path))
        self.budget_service.declare_budget_capabilities(
            node_id="node-budget-1",
            payload={
                "node_id": "node-budget-1",
                "currency": "USD",
                "compute_unit": "cost_units",
                "default_period": "monthly",
                "supports_money_budget": True,
                "supports_compute_budget": True,
                "supports_customer_allocations": True,
                "supports_provider_allocations": True,
                "supported_providers": ["openai"],
            },
        )
        self._configure_budget()

        app = FastAPI()
        app.include_router(
            build_scheduler_router(
                SchedulerEngine(SchedulerStore(), total_capacity_units=100, reserve_units=0),
                node_budget_service=self.budget_service,
                audit_store=self.audit_store,
            ),
            prefix="/api/system/scheduler",
        )
        self.client = TestClient(app)

        self.routing_service.record_provider_intelligence(
            node_id="node-budget-1",
            provider_intelligence=[
                {
                    "provider": "openai",
                    "available_models": [
                        {
                            "model_id": "gpt-4o-mini",
                            "pricing": {"input_per_1k": 0.002, "output_per_1k": 0.004, "per_request": 0.01},
                            "latency_metrics": {"p50_ms": 120.0},
                        }
                    ],
                }
            ],
            node_available=True,
            source="provider_capability_report",
        )

    def _configure_budget(
        self,
        *,
        shared_customer_pool: bool = False,
        shared_provider_pool: bool = False,
        compute_unit: str = "cost_units",
        node_compute_limit: float = 100.0,
        customer_compute_limit: float = 30.0,
        provider_compute_limit: float = 80.0,
    ) -> None:
        self.budget_service.configure_node_budget(
            node_id="node-budget-1",
            node_budget={
                "currency": "USD",
                "compute_unit": compute_unit,
                "period": "monthly",
                "reset_policy": "calendar",
                "enforcement_mode": "hard_stop",
                "shared_customer_pool": shared_customer_pool,
                "shared_provider_pool": shared_provider_pool,
                "node_money_limit": 10.0,
                "node_compute_limit": node_compute_limit,
            },
            customer_allocations=[{"subject_id": "cust-a", "money_limit": 3.3, "compute_limit": customer_compute_limit}],
            provider_allocations=[{"subject_id": "openai", "money_limit": 8.0, "compute_limit": provider_compute_limit}],
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _audit_events(self) -> list[dict]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _submit_budgeted_job(
        self,
        *,
        money_estimate: float = 2.5,
        compute_units: float | None = None,
        customer_id: str | None = "cust-a",
        provider: str | None = "openai",
    ):
        budget_scope = {
            "node_id": "node-budget-1",
            "money_estimate": money_estimate,
            **({"compute_units": compute_units} if compute_units is not None else {}),
        }
        if customer_id is not None:
            budget_scope["customer_id"] = customer_id
        if provider is not None:
            budget_scope["provider"] = provider
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        res = self.client.post(
            "/api/system/scheduler/queue/jobs/submit",
            json={
                "addon_id": "vision",
                "job_type": "generate",
                "cost_units": 7,
                "earliest_start_at": future,
                "payload": {
                    "budget_scope": budget_scope
                },
            },
        )
        return res

    def test_submit_creates_budget_reservation(self) -> None:
        created = self._submit_budgeted_job()
        self.assertEqual(created.status_code, 200, created.text)
        job_id = created.json()["job_id"]

        reservation = self.budget_service.get_reservation_by_job(job_id)
        self.assertIsNotNone(reservation)
        assert reservation is not None
        self.assertEqual(reservation["state"], "reserved")
        self.assertEqual(reservation["node_id"], "node-budget-1")
        self.assertEqual(reservation["customer_id"], "cust-a")
        self.assertEqual(reservation["provider_id"], "openai")
        self.assertEqual(reservation["money_reserved"], 2.5)
        self.assertEqual(reservation["compute_reserved"], 7.0)

    def test_done_completion_finalizes_budget_reservation(self) -> None:
        created = self._submit_budgeted_job()
        self.assertEqual(created.status_code, 200, created.text)
        job_id = created.json()["job_id"]

        completed = self.client.post(
            f"/api/system/scheduler/queue/jobs/{job_id}/complete",
            json={"status": "DONE", "actual_money_spend": 1.7, "actual_compute_spend": 5.0},
        )
        self.assertEqual(completed.status_code, 200, completed.text)

        reservation = self.budget_service.get_reservation_by_job(job_id)
        self.assertIsNotNone(reservation)
        assert reservation is not None
        self.assertEqual(reservation["state"], "finalized")
        self.assertEqual(reservation["money_actual"], 1.7)
        self.assertEqual(reservation["compute_actual"], 5.0)

    def test_cancel_releases_budget_reservation(self) -> None:
        created = self._submit_budgeted_job()
        self.assertEqual(created.status_code, 200, created.text)
        job_id = created.json()["job_id"]

        canceled = self.client.post(f"/api/system/scheduler/queue/jobs/{job_id}/cancel")
        self.assertEqual(canceled.status_code, 200, canceled.text)

        reservation = self.budget_service.get_reservation_by_job(job_id)
        self.assertIsNotNone(reservation)
        assert reservation is not None
        self.assertEqual(reservation["state"], "released")
        self.assertEqual(reservation["release_reason"], "canceled")

    def test_rejects_when_node_budget_would_be_exceeded(self) -> None:
        first = self._submit_budgeted_job(money_estimate=6.0, compute_units=60.0, customer_id=None, provider=None)
        self.assertEqual(first.status_code, 200, first.text)

        second = self._submit_budgeted_job(money_estimate=5.0, compute_units=50.0, customer_id=None, provider=None)
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(second.json()["detail"]["error"], "node_money_budget_exceeded")

    def test_rejects_when_customer_budget_would_be_exceeded(self) -> None:
        first = self._submit_budgeted_job(money_estimate=2.0, compute_units=20.0)
        self.assertEqual(first.status_code, 200, first.text)

        second = self._submit_budgeted_job(money_estimate=1.5, compute_units=15.0)
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(second.json()["detail"]["error"], "customer_money_budget_exceeded")

    def test_rejects_when_provider_budget_would_be_exceeded(self) -> None:
        first = self._submit_budgeted_job(money_estimate=5.0, compute_units=40.0, customer_id=None)
        self.assertEqual(first.status_code, 200, first.text)

        second = self._submit_budgeted_job(money_estimate=3.5, compute_units=35.0, customer_id=None)
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(second.json()["detail"]["error"], "provider_money_budget_exceeded")

    def test_shared_customer_pool_allows_borrowing_above_customer_slice(self) -> None:
        self._configure_budget(shared_customer_pool=True)

        first = self._submit_budgeted_job(money_estimate=2.5, compute_units=20.0)
        self.assertEqual(first.status_code, 200, first.text)

        second = self._submit_budgeted_job(money_estimate=2.5, compute_units=20.0)
        self.assertEqual(second.status_code, 200, second.text)

    def test_shared_provider_pool_allows_borrowing_above_provider_slice(self) -> None:
        self._configure_budget(shared_provider_pool=True)

        first = self._submit_budgeted_job(money_estimate=5.0, compute_units=40.0, customer_id=None)
        self.assertEqual(first.status_code, 200, first.text)

        second = self._submit_budgeted_job(money_estimate=3.5, compute_units=35.0, customer_id=None)
        self.assertEqual(second.status_code, 200, second.text)

    def test_hard_slice_customer_requires_explicit_allocation_when_customer_slices_exist(self) -> None:
        created = self._submit_budgeted_job(customer_id="cust-missing")
        self.assertEqual(created.status_code, 400, created.text)
        self.assertEqual(created.json()["detail"]["error"], "customer_budget_allocation_required")

    def test_hard_slice_provider_requires_explicit_allocation_when_provider_slices_exist(self) -> None:
        created = self._submit_budgeted_job(customer_id=None, provider="anthropic")
        self.assertEqual(created.status_code, 400, created.text)
        self.assertEqual(created.json()["detail"]["error"], "provider_budget_allocation_required")

    def test_shared_customer_pool_allows_unassigned_customer(self) -> None:
        self._configure_budget(shared_customer_pool=True)

        created = self._submit_budgeted_job(customer_id="cust-missing")
        self.assertEqual(created.status_code, 200, created.text)

    def test_shared_provider_pool_allows_unassigned_provider(self) -> None:
        self._configure_budget(shared_provider_pool=True)

        created = self._submit_budgeted_job(customer_id=None, provider="anthropic")
        self.assertEqual(created.status_code, 200, created.text)

    def test_estimates_money_and_compute_from_routing_metadata_and_payload(self) -> None:
        created = self.client.post(
            "/api/system/scheduler/queue/jobs/submit",
            json={
                "addon_id": "vision",
                "job_type": "generate",
                "cost_units": 9,
                "payload": {
                    "budget_scope": {
                        "node_id": "node-budget-1",
                        "customer_id": "cust-a",
                        "provider": "openai",
                        "model_id": "gpt-4o-mini",
                    },
                    "input_tokens": 1000,
                    "output_tokens": 500,
                },
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        reservation = self.budget_service.get_reservation_by_job(created.json()["job_id"])
        self.assertIsNotNone(reservation)
        assert reservation is not None
        self.assertEqual(reservation["money_reserved"], 0.014)
        self.assertEqual(reservation["compute_reserved"], 9.0)

    def test_usage_summary_reflects_reserved_and_actual_amounts(self) -> None:
        created = self._submit_budgeted_job(money_estimate=2.0, compute_units=6.0)
        self.assertEqual(created.status_code, 200, created.text)
        job_id = created.json()["job_id"]

        summary = self.budget_service.get_bundle("node-budget-1")["usage_summary"]["node"]
        self.assertEqual(summary["reserved_money"], 2.0)
        self.assertEqual(summary["remaining_money"], 8.0)

        finalized = self.client.post(
            f"/api/system/scheduler/queue/jobs/{job_id}/complete",
            json={"status": "DONE", "actual_money_spend": 1.25, "actual_compute_spend": 4.0},
        )
        self.assertEqual(finalized.status_code, 200, finalized.text)
        summary = self.budget_service.get_bundle("node-budget-1")["usage_summary"]["node"]
        self.assertEqual(summary["reserved_money"], 0.0)
        self.assertEqual(summary["actual_money"], 1.25)
        self.assertEqual(summary["remaining_money"], 8.75)
        event_types = [item["event_type"] for item in self._audit_events()]
        self.assertIn("node_budget_reservation_created", event_types)
        self.assertIn("node_budget_reservation_finalized", event_types)

    def test_usage_summary_emits_threshold_alerts(self) -> None:
        created = self._submit_budgeted_job(money_estimate=8.5, compute_units=85.0, customer_id=None, provider=None)
        self.assertEqual(created.status_code, 200, created.text)

        usage = self.budget_service.usage_inspection("node-budget-1")
        node_alerts = usage["usage_summary"]["node"]["alerts"]
        self.assertTrue(any(alert["metric"] == "money" and alert["threshold"] == 0.8 for alert in node_alerts))
        self.assertTrue(any(alert["metric"] == "compute" and alert["threshold"] == 0.8 for alert in node_alerts))
        self.assertGreaterEqual(len(usage["usage_summary"]["alerts"]), 2)

    def test_estimates_compute_from_tokens_when_budget_uses_token_units(self) -> None:
        self._configure_budget(
            compute_unit="tokens",
            node_compute_limit=5000.0,
            customer_compute_limit=5000.0,
            provider_compute_limit=5000.0,
        )
        created = self.client.post(
            "/api/system/scheduler/queue/jobs/submit",
            json={
                "addon_id": "vision",
                "job_type": "generate",
                "cost_units": 9,
                "payload": {
                    "budget_scope": {
                        "node_id": "node-budget-1",
                        "customer_id": "cust-a",
                        "provider": "openai",
                        "model_id": "gpt-4o-mini",
                    },
                    "input_tokens": 1000,
                    "output_tokens": 500,
                },
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        reservation = self.budget_service.get_reservation_by_job(created.json()["job_id"])
        self.assertIsNotNone(reservation)
        assert reservation is not None
        self.assertEqual(reservation["compute_reserved"], 1500.0)


if __name__ == "__main__":
    unittest.main()

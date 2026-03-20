import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.system.onboarding import NodeBudgetService, NodeBudgetStore
from app.system.scheduler.engine import SchedulerEngine
from app.system.scheduler.router import build_scheduler_router
from app.system.scheduler.store import SchedulerStore


class TestSchedulerBudgetReservations(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        base = Path(self.tmpdir.name)
        self.budget_store = NodeBudgetStore(path=base / "node_budgets.json")
        self.budget_service = NodeBudgetService(self.budget_store)
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
        self.budget_service.configure_node_budget(
            node_id="node-budget-1",
            node_budget={
                "currency": "USD",
                "compute_unit": "cost_units",
                "period": "monthly",
                "reset_policy": "calendar",
                "enforcement_mode": "hard_stop",
                "node_money_limit": 10.0,
                "node_compute_limit": 100.0,
            },
            customer_allocations=[{"subject_id": "cust-a", "money_limit": 3.3, "compute_limit": 30.0}],
            provider_allocations=[{"subject_id": "openai", "money_limit": 8.0, "compute_limit": 80.0}],
        )

        app = FastAPI()
        app.include_router(
            build_scheduler_router(
                SchedulerEngine(SchedulerStore(), total_capacity_units=100, reserve_units=0),
                node_budget_service=self.budget_service,
            ),
            prefix="/api/system/scheduler",
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

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


if __name__ == "__main__":
    unittest.main()

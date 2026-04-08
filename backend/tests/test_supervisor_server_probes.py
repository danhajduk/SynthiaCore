from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.supervisor.models import SupervisorAdmissionContextSummary
from app.supervisor.server import create_supervisor_app


class _FakeSupervisor:
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    def admission_summary(self) -> SupervisorAdmissionContextSummary:
        return SupervisorAdmissionContextSummary(
            admission_state="ready" if self._ready else "degraded",
            execution_host_ready=self._ready,
            unavailable_reason=None if self._ready else "host_capacity_unavailable",
            host_busy_rating=1,
            total_capacity_units=100,
            available_capacity_units=25 if self._ready else 0,
            managed_node_count=0,
            healthy_managed_node_count=0,
        )


class TestSupervisorServerProbes(unittest.TestCase):
    def _client(self, ready: bool) -> TestClient:
        app = create_supervisor_app()
        app.state.supervisor_service = _FakeSupervisor(ready)
        return TestClient(app)

    def test_health_probe(self) -> None:
        client = self._client(True)
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_ready_probe_ok(self) -> None:
        client = self._client(True)
        response = client.get("/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")

    def test_ready_probe_degraded(self) -> None:
        client = self._client(False)
        response = client.get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "degraded")


if __name__ == "__main__":
    unittest.main()

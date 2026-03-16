from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.supervisor import (
    HostIdentitySummary,
    HostResourceSummary,
    ManagedNodeSummary,
    ProcessResourceSummary,
    SupervisorAdmissionContextSummary,
    SupervisorHealthSummary,
    SupervisorInfoSummary,
    SupervisorNodeActionResult,
    SupervisorOwnershipBoundary,
    SupervisorRuntimeSummary,
    build_supervisor_router,
)


class _FakeSupervisorService:
    def _node(self) -> ManagedNodeSummary:
        return ManagedNodeSummary(
            node_id="mqtt",
            lifecycle_state="running",
            desired_state="running",
            runtime_state="running",
            health_status="healthy",
            active_version="1.0.0",
            running=True,
            last_action="start",
            last_action_at="2026-03-16T00:00:00Z",
        )

    def _host(self) -> HostIdentitySummary:
        return HostIdentitySummary(host_id="host-a", hostname="host-a", runtime_provider="docker")

    def _resources(self) -> HostResourceSummary:
        return HostResourceSummary(
            uptime_s=1.0,
            load_1m=0.1,
            load_5m=0.2,
            load_15m=0.3,
            cpu_percent_total=2.0,
            cpu_cores_logical=4,
            memory_total_bytes=8,
            memory_available_bytes=4,
            memory_percent=50.0,
            root_disk_total_bytes=100,
            root_disk_free_bytes=40,
            root_disk_percent=60.0,
        )

    def health_summary(self) -> SupervisorHealthSummary:
        return SupervisorHealthSummary(
            status="ok",
            host=self._host(),
            resources=self._resources(),
            managed_node_count=1,
            healthy_node_count=1,
            unhealthy_node_count=0,
        )

    def info_summary(self) -> SupervisorInfoSummary:
        return SupervisorInfoSummary(
            supervisor_id="host-a",
            host=self._host(),
            resources=self._resources(),
            boundaries=SupervisorOwnershipBoundary(owns=["runtime"], depends_on_core_for=["policy"]),
            managed_node_count=1,
            managed_nodes=[self._node()],
        )

    def resources_summary(self) -> HostResourceSummary:
        return self._resources()

    def runtime_summary(self) -> SupervisorRuntimeSummary:
        return SupervisorRuntimeSummary(
            host=self._host(),
            resources=self._resources(),
            process=ProcessResourceSummary(rss_bytes=1, cpu_percent=0.0, open_fds=1, threads=1),
            managed_node_count=1,
            managed_nodes=[self._node()],
        )

    def admission_summary(self) -> SupervisorAdmissionContextSummary:
        return SupervisorAdmissionContextSummary(
            admission_state="ready",
            execution_host_ready=True,
            host_busy_rating=1,
            total_capacity_units=100,
            available_capacity_units=75,
            managed_node_count=1,
            healthy_managed_node_count=1,
        )

    def list_managed_nodes(self) -> list[ManagedNodeSummary]:
        return [self._node()]

    def start_managed_node(self, node_id: str) -> SupervisorNodeActionResult:
        return SupervisorNodeActionResult(action="start", node=self._node())

    def stop_managed_node(self, node_id: str) -> SupervisorNodeActionResult:
        return SupervisorNodeActionResult(action="stop", node=self._node())

    def restart_managed_node(self, node_id: str) -> SupervisorNodeActionResult:
        return SupervisorNodeActionResult(action="restart", node=self._node())


class TestSupervisorRouterContract(unittest.TestCase):
    def test_supervisor_host_api_surface(self) -> None:
        app = FastAPI()
        app.include_router(build_supervisor_router(_FakeSupervisorService()), prefix="/api")
        client = TestClient(app)

        info = client.get("/api/supervisor/info")
        self.assertEqual(info.status_code, 200)
        self.assertEqual(info.json()["boundaries"]["owns"], ["runtime"])
        self.assertEqual(client.get("/api/supervisor/admission").json()["admission_state"], "ready")
        self.assertEqual(client.get("/api/supervisor/resources").status_code, 200)
        self.assertEqual(client.get("/api/supervisor/runtime").status_code, 200)
        self.assertEqual(client.get("/api/supervisor/nodes").json()["items"][0]["node_id"], "mqtt")
        self.assertEqual(client.post("/api/supervisor/nodes/mqtt/start").json()["action"], "start")
        self.assertEqual(client.post("/api/supervisor/nodes/mqtt/stop").json()["action"], "stop")
        self.assertEqual(client.post("/api/supervisor/nodes/mqtt/restart").json()["action"], "restart")


if __name__ == "__main__":
    unittest.main()

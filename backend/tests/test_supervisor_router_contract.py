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
    SupervisorRegisteredRuntimeSummary,
    SupervisorRuntimeActionResult,
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

    def admission_summary(
        self,
        *,
        total_capacity_units: int = 100,
        reserve_units: int = 5,
        headroom_pct: float = 0.05,
    ) -> SupervisorAdmissionContextSummary:
        return SupervisorAdmissionContextSummary(
            admission_state="ready",
            execution_host_ready=True,
            host_busy_rating=1,
            total_capacity_units=total_capacity_units,
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

    def _runtime(self) -> SupervisorRegisteredRuntimeSummary:
        return SupervisorRegisteredRuntimeSummary(
            node_id="node-1",
            node_name="office-node",
            node_type="ai",
            desired_state="running",
            runtime_state="running",
            lifecycle_state="running",
            health_status="healthy",
            freshness_state="online",
            host_id="host-a",
            hostname="host-a",
        )

    def list_registered_runtimes(self) -> list[SupervisorRegisteredRuntimeSummary]:
        return [self._runtime()]

    def get_registered_runtime(self, node_id: str) -> SupervisorRegisteredRuntimeSummary:
        return self._runtime()

    def register_runtime(self, body) -> SupervisorRegisteredRuntimeSummary:
        return self._runtime()

    def heartbeat_runtime(self, body) -> SupervisorRegisteredRuntimeSummary:
        return self._runtime()

    def start_registered_runtime(self, node_id: str) -> SupervisorRuntimeActionResult:
        return SupervisorRuntimeActionResult(action="start", runtime=self._runtime())

    def stop_registered_runtime(self, node_id: str) -> SupervisorRuntimeActionResult:
        return SupervisorRuntimeActionResult(action="stop", runtime=self._runtime())

    def restart_registered_runtime(self, node_id: str) -> SupervisorRuntimeActionResult:
        return SupervisorRuntimeActionResult(action="restart", runtime=self._runtime())

    def get_runtime_state(self, runtime_id: str) -> dict[str, object]:
        return {"exists": runtime_id == "cloudflared"}

    def apply_cloudflared_config(self, config: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "runtime_state": "configured", "config_path": "/tmp/cloudflared.yaml"}


class TestSupervisorRouterContract(unittest.TestCase):
    def test_supervisor_host_api_surface(self) -> None:
        app = FastAPI()
        app.include_router(build_supervisor_router(_FakeSupervisorService()), prefix="/api")
        client = TestClient(app)

        info = client.get("/api/supervisor/info")
        self.assertEqual(info.status_code, 200)
        self.assertEqual(info.json()["boundaries"]["owns"], ["runtime"])
        self.assertEqual(client.get("/api/supervisor/admission").json()["admission_state"], "ready")
        self.assertEqual(client.get("/api/supervisor/admission?total_capacity_units=250").json()["total_capacity_units"], 250)
        self.assertEqual(client.get("/api/supervisor/resources").status_code, 200)
        self.assertEqual(client.get("/api/supervisor/runtime").status_code, 200)
        self.assertTrue(client.get("/api/supervisor/runtime/cloudflared").json()["exists"])
        self.assertFalse(client.get("/api/supervisor/runtime/unknown").json()["exists"])
        self.assertTrue(client.post("/api/supervisor/runtime/cloudflared/apply", json={"ok": True}).json()["ok"])
        self.assertEqual(client.get("/api/supervisor/nodes").json()["items"][0]["node_id"], "mqtt")
        self.assertEqual(client.post("/api/supervisor/nodes/mqtt/start").json()["action"], "start")
        self.assertEqual(client.post("/api/supervisor/nodes/mqtt/stop").json()["action"], "stop")
        self.assertEqual(client.post("/api/supervisor/nodes/mqtt/restart").json()["action"], "restart")
        self.assertEqual(client.get("/api/supervisor/runtimes").json()["items"][0]["node_id"], "node-1")
        self.assertEqual(client.get("/api/supervisor/runtimes/node-1").json()["runtime"]["node_name"], "office-node")
        self.assertEqual(client.post("/api/supervisor/runtimes/register", json={"node_id": "node-1", "node_name": "office-node", "node_type": "ai"}).json()["node_id"], "node-1")
        self.assertEqual(client.post("/api/supervisor/runtimes/heartbeat", json={"node_id": "node-1"}).json()["node_id"], "node-1")
        self.assertEqual(client.post("/api/supervisor/runtimes/node-1/start").json()["action"], "start")


if __name__ == "__main__":
    unittest.main()

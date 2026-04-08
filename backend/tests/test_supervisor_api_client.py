from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx

from app.supervisor.client import SupervisorApiClient, SupervisorClientConfig
from app.supervisor.runtime_store import SupervisorRuntimeNodesStore


class TestSupervisorApiClient(unittest.TestCase):
    def test_supervisor_client_requests(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/supervisor/admission":
                params = dict(request.url.params)
                assert params.get("total_capacity_units") == "50"
                assert params.get("reserve_units") == "5"
                return httpx.Response(
                    200,
                    json={
                        "admission_state": "ready",
                        "execution_host_ready": True,
                        "unavailable_reason": None,
                        "host_busy_rating": 1,
                        "total_capacity_units": 50,
                        "available_capacity_units": 25,
                        "managed_node_count": 1,
                        "healthy_managed_node_count": 1,
                    },
                )
            if request.url.path == "/api/supervisor/runtimes":
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "node_id": "node-1",
                                "node_name": "office-node",
                                "node_type": "ai",
                                "desired_state": "running",
                                "runtime_state": "running",
                                "lifecycle_state": "running",
                                "health_status": "healthy",
                                "freshness_state": "online",
                            }
                        ]
                    },
                )
            if request.url.path == "/api/supervisor/runtime/cloudflared":
                return httpx.Response(200, json={"exists": True})
            if request.url.path == "/api/supervisor/runtime/cloudflared/apply":
                return httpx.Response(200, json={"ok": True, "runtime_state": "configured"})
            if request.url.path == "/api/supervisor/core/runtimes":
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "runtime_id": "core-api",
                                "runtime_name": "Hexe Core API",
                                "runtime_kind": "core_service",
                                "management_mode": "monitor",
                                "desired_state": "running",
                                "runtime_state": "running",
                                "lifecycle_state": "running",
                                "health_status": "healthy",
                                "freshness_state": "online",
                            }
                        ]
                    },
                )
            if request.url.path == "/api/supervisor/core/runtimes/register":
                return httpx.Response(
                    200,
                    json={
                        "runtime_id": "core-api",
                        "runtime_name": "Hexe Core API",
                        "runtime_kind": "core_service",
                        "management_mode": "monitor",
                        "desired_state": "running",
                        "runtime_state": "running",
                        "lifecycle_state": "running",
                        "health_status": "healthy",
                        "freshness_state": "online",
                    },
                )
            if request.url.path == "/api/supervisor/core/runtimes/heartbeat":
                return httpx.Response(
                    200,
                    json={
                        "runtime_id": "core-api",
                        "runtime_name": "Hexe Core API",
                        "runtime_kind": "core_service",
                        "management_mode": "monitor",
                        "desired_state": "running",
                        "runtime_state": "running",
                        "lifecycle_state": "running",
                        "health_status": "healthy",
                        "freshness_state": "online",
                    },
                )
            return httpx.Response(404, json={"detail": "not_found"})

        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport, base_url="http://supervisor")
        config = SupervisorClientConfig(
            transport="http",
            base_url="http://supervisor",
            unix_socket="/run/hexe/supervisor.sock",
            timeout_s=2.0,
        )
        client = SupervisorApiClient(config=config, client=http_client)

        admission = client.admission_summary(total_capacity_units=50, reserve_units=5, headroom_pct=0.05)
        self.assertIsNotNone(admission)
        self.assertEqual(admission.total_capacity_units, 50)

        runtimes = client.list_registered_runtimes()
        self.assertIsNotNone(runtimes)
        self.assertEqual(runtimes[0].node_id, "node-1")

        runtime_state = client.get_runtime_state("cloudflared")
        self.assertTrue(runtime_state["exists"])

        apply_result = client.apply_cloudflared_config({"rendered": True})
        self.assertTrue(apply_result["ok"])

        core_created = client.register_core_runtime({"runtime_id": "core-api", "runtime_name": "Hexe Core API"})
        self.assertIsNotNone(core_created)
        self.assertEqual(core_created.runtime_id, "core-api")

        core_heartbeat = client.heartbeat_core_runtime({"runtime_id": "core-api"})
        self.assertIsNotNone(core_heartbeat)
        self.assertEqual(core_heartbeat.runtime_name, "Hexe Core API")

        core_runtimes = client.list_core_runtimes()
        self.assertIsNotNone(core_runtimes)
        self.assertEqual(core_runtimes[0].runtime_id, "core-api")

        with tempfile.TemporaryDirectory() as tmp:
            store = SupervisorRuntimeNodesStore(path=Path(tmp) / "runtime.json")
            self.assertTrue(client.refresh_runtime_store(store))
            self.assertIsNotNone(store.get("node-1"))


if __name__ == "__main__":
    unittest.main()

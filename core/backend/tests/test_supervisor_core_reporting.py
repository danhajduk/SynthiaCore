import asyncio
import os
import unittest
from unittest.mock import patch

import httpx

from app.supervisor import (
    HostIdentitySummary,
    HostResourceSummary,
    ProcessResourceSummary,
    SupervisorCoreRuntimeSummary,
    SupervisorHealthSummary,
    SupervisorRegisteredRuntimeSummary,
    SupervisorRuntimeSummary,
)
from app.supervisor.server import _build_core_heartbeat_payload, _post_supervisor_payload


def _host() -> HostIdentitySummary:
    return HostIdentitySummary(host_id="host-a", hostname="host-a", runtime_provider="docker")


def _resources() -> HostResourceSummary:
    return HostResourceSummary(
        uptime_s=1.0,
        load_1m=0.0,
        load_5m=0.0,
        load_15m=0.0,
        cpu_percent_total=1.0,
        cpu_cores_logical=8,
        memory_total_bytes=16,
        memory_available_bytes=8,
        memory_percent=50.0,
        gpu_count=1,
        gpu_utilization_percent=42.0,
        gpu_memory_percent=25.0,
        gpu_devices=[{"name": "NVIDIA RTX", "utilization_percent": 42.0}],
    )


class _FakeSupervisor:
    def health_summary(self) -> SupervisorHealthSummary:
        return SupervisorHealthSummary(
            status="ok",
            host=_host(),
            resources=_resources(),
            managed_node_count=0,
            healthy_node_count=0,
            unhealthy_node_count=0,
        )

    def resources_summary(self) -> HostResourceSummary:
        return _resources()

    def runtime_summary(self) -> SupervisorRuntimeSummary:
        return SupervisorRuntimeSummary(
            host=_host(),
            resources=_resources(),
            process=ProcessResourceSummary(),
            managed_node_count=0,
            managed_nodes=[],
        )

    def list_registered_runtimes(self) -> list[SupervisorRegisteredRuntimeSummary]:
        return [
            SupervisorRegisteredRuntimeSummary(
                node_id="node-ai",
                node_name="AI Node",
                node_type="ai-node",
                desired_state="running",
                runtime_state="running",
                lifecycle_state="running",
                health_status="healthy",
            )
        ]

    def list_core_runtimes(self) -> list[SupervisorCoreRuntimeSummary]:
        return [
            SupervisorCoreRuntimeSummary(
                runtime_id="addon:mqtt",
                runtime_name="Hexe MQTT",
                runtime_kind="addon",
                desired_state="running",
                runtime_state="running",
                lifecycle_state="running",
                health_status="healthy",
            )
        ]


class TestSupervisorCoreReporting(unittest.TestCase):
    def test_heartbeat_payload_includes_remote_runtime_details_and_gpu_stats(self) -> None:
        payload = _build_core_heartbeat_payload(_FakeSupervisor())

        self.assertEqual(payload["registered_runtime_count"], 1)
        self.assertEqual(payload["core_runtime_count"], 1)
        self.assertEqual(payload["registered_runtimes"][0]["node_id"], "node-ai")
        self.assertEqual(payload["core_runtimes"][0]["runtime_id"], "addon:mqtt")
        resources = payload["resources"]
        self.assertEqual(resources["gpu_count"], 1)
        self.assertEqual(resources["gpu_devices"][0]["name"], "NVIDIA RTX")

    def test_supervisor_token_kind_uses_supervisor_header(self) -> None:
        captured_headers: dict[str, str] = {}

        async def run() -> bool:
            def handler(request: httpx.Request) -> httpx.Response:
                captured_headers.update(dict(request.headers))
                return httpx.Response(200, json={"ok": True})

            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport) as client:
                kwargs = {
                    "core_url": "http://core",
                    "token": "hexe_sup_report_test",
                    "path": "/api/system/supervisors/heartbeat",
                    "payload": {"supervisor_id": "host-a"},
                }
                return await _post_supervisor_payload(client, **kwargs)

        with patch.dict(os.environ, {"HEXE_SUPERVISOR_CORE_TOKEN_KIND": "supervisor"}, clear=False):
            self.assertTrue(asyncio.run(run()))

        self.assertEqual(captured_headers.get("x-supervisor-token"), "hexe_sup_report_test")
        self.assertNotIn("x-admin-token", captured_headers)

    def test_admin_token_kind_uses_admin_header(self) -> None:
        captured_headers: dict[str, str] = {}

        async def run() -> bool:
            def handler(request: httpx.Request) -> httpx.Response:
                captured_headers.update(dict(request.headers))
                return httpx.Response(200, json={"ok": True})

            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport) as client:
                kwargs = {
                    "core_url": "http://core",
                    "token": "admin-token",
                    "path": "/api/system/supervisors/heartbeat",
                    "payload": {"supervisor_id": "host-a"},
                }
                return await _post_supervisor_payload(client, **kwargs)

        with patch.dict(os.environ, {"HEXE_SUPERVISOR_CORE_TOKEN_KIND": "admin"}, clear=False):
            self.assertTrue(asyncio.run(run()))

        self.assertEqual(captured_headers.get("x-admin-token"), "admin-token")
        self.assertNotIn("x-supervisor-token", captured_headers)


if __name__ == "__main__":
    unittest.main()

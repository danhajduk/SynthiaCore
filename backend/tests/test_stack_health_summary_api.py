from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from subprocess import CompletedProcess

from app.system import stack_health
from app.system.stack_health import build_stack_health_router


class _FakeSnapshot:
    def __init__(self, active_leases: int, queue_depths: dict[str, int]) -> None:
        self.active_leases = active_leases
        self.queue_depths = queue_depths


class _FakeScheduler:
    async def snapshot(self) -> _FakeSnapshot:
        return _FakeSnapshot(active_leases=2, queue_depths={"default": 1})


class _FakeMqtt:
    async def status(self) -> dict[str, object]:
        return {
            "connected": True,
            "enabled": True,
            "last_message_at": "2026-03-07T16:00:00Z",
        }


class _FakeAddon:
    def __init__(self, health_status: str) -> None:
        self.health_status = health_status


class _FakeRegistry:
    def __init__(self) -> None:
        self.addons = {"hello_world": object()}
        self.registered = {
            "hello_world": _FakeAddon("healthy"),
            "mqtt": _FakeAddon("unhealthy"),
        }

    def is_enabled(self, addon_id: str) -> bool:
        return addon_id != "disabled_addon"


class _FakeRate:
    def __init__(self, rx_Bps: float, tx_Bps: float) -> None:
        self.rx_Bps = rx_Bps
        self.tx_Bps = tx_Bps


class _FakeNet:
    def __init__(self, total_rate: _FakeRate | None = None, total: object | None = None) -> None:
        self.total_rate = total_rate
        self.total = total


class _FakeCounters:
    def __init__(
        self,
        *,
        bytes_sent: int = 0,
        bytes_recv: int = 0,
        packets_sent: int = 0,
        packets_recv: int = 0,
        errin: int = 0,
        errout: int = 0,
        dropin: int = 0,
        dropout: int = 0,
    ) -> None:
        self.bytes_sent = bytes_sent
        self.bytes_recv = bytes_recv
        self.packets_sent = packets_sent
        self.packets_recv = packets_recv
        self.errin = errin
        self.errout = errout
        self.dropin = dropin
        self.dropout = dropout


class _FakeStats:
    def __init__(self, total_rate: _FakeRate | None = None, total: object | None = None) -> None:
        self.net = _FakeNet(total_rate=total_rate, total=total if total is not None else _FakeCounters())
        self.services = {}


class TestStackHealthSummaryApi(unittest.TestCase):
    def setUp(self) -> None:
        self.old_local = os.environ.get("SYNTHIA_LOCAL_NETWORK_CHECK_HOST")
        self.old_internet = os.environ.get("SYNTHIA_INTERNET_CHECK_HOST")

        os.environ["SYNTHIA_LOCAL_NETWORK_CHECK_HOST"] = ""
        os.environ["SYNTHIA_INTERNET_CHECK_HOST"] = ""
        stack_health._sampler._speed_cache = None
        stack_health._sampler._connectivity_cache = None

    def tearDown(self) -> None:
        if self.old_local is None:
            os.environ.pop("SYNTHIA_LOCAL_NETWORK_CHECK_HOST", None)
        else:
            os.environ["SYNTHIA_LOCAL_NETWORK_CHECK_HOST"] = self.old_local

        if self.old_internet is None:
            os.environ.pop("SYNTHIA_INTERNET_CHECK_HOST", None)
        else:
            os.environ["SYNTHIA_INTERNET_CHECK_HOST"] = self.old_internet

        stack_health._sampler._speed_cache = None
        stack_health._sampler._connectivity_cache = None

    @patch("app.system.stack_health.subprocess.run")
    def test_stack_summary_returns_dashboard_contract(self, mock_run) -> None:
        # Speed test may be unavailable; contract still returns stable summary payload.
        mock_run.return_value = CompletedProcess(args=["speedtest-cli"], returncode=1, stdout="", stderr="missing")
        app = FastAPI()
        app.include_router(build_stack_health_router(), prefix="/api/system")
        app.state.scheduler_engine = _FakeScheduler()
        app.state.mqtt_manager = _FakeMqtt()
        app.state.addon_registry = _FakeRegistry()
        app.state.latest_stats = _FakeStats()

        client = TestClient(app)
        res = client.get("/api/system/stack/summary")
        self.assertEqual(res.status_code, 200, res.text)

        payload = res.json()
        self.assertIn("status", payload)
        self.assertIn("subsystems", payload)
        self.assertIn("connectivity", payload)
        self.assertIn("samples", payload)

        self.assertEqual(payload["subsystems"]["mqtt"]["state"], "connected")
        self.assertEqual(payload["subsystems"]["scheduler"]["state"], "running")
        self.assertEqual(payload["subsystems"]["workers"]["active_count"], 2)
        self.assertEqual(payload["subsystems"]["addons"]["installed_count"], 2)
        self.assertEqual(payload["subsystems"]["addons"]["unhealthy_count"], 1)

        self.assertEqual(payload["connectivity"]["network"]["state"], "not_configured")
        self.assertEqual(payload["connectivity"]["internet"]["state"], "not_configured")
        self.assertEqual(payload["samples"]["internet_speed"]["state"], "unavailable")
        self.assertEqual(payload["samples"]["network_throughput"]["state"], "warming_up")
        self.assertEqual(payload["samples"]["network_metrics"]["state"], "ok")

    @patch("app.system.stack_health.subprocess.run")
    def test_stack_summary_reports_speedtest_cli_result(self, mock_run) -> None:
        mock_run.return_value = CompletedProcess(
            args=["speedtest-cli"],
            returncode=0,
            stdout='{"download": 12500000, "upload": 5000000, "ping": 23.6}',
            stderr="",
        )
        app = FastAPI()
        app.include_router(build_stack_health_router(), prefix="/api/system")
        app.state.scheduler_engine = _FakeScheduler()
        app.state.mqtt_manager = _FakeMqtt()
        app.state.addon_registry = _FakeRegistry()
        app.state.latest_stats = _FakeStats(
            total_rate=_FakeRate(rx_Bps=1_250_000.0, tx_Bps=625_000.0),
            total=_FakeCounters(
                bytes_sent=1000,
                bytes_recv=2000,
                packets_sent=30,
                packets_recv=40,
                errin=1,
                errout=2,
                dropin=3,
                dropout=4,
            ),
        )

        client = TestClient(app)
        res = client.get("/api/system/stack/summary")
        self.assertEqual(res.status_code, 200, res.text)

        payload = res.json()
        self.assertEqual(payload["samples"]["network_throughput"]["state"], "ok")
        self.assertEqual(payload["samples"]["network_throughput"]["rx_Bps"], 1250000.0)
        self.assertEqual(payload["samples"]["network_throughput"]["tx_Bps"], 625000.0)
        self.assertEqual(payload["samples"]["network_metrics"]["state"], "ok")
        self.assertEqual(payload["samples"]["network_metrics"]["bytes_recv"], 2000)
        self.assertEqual(payload["samples"]["network_metrics"]["bytes_sent"], 1000)
        self.assertEqual(payload["samples"]["network_metrics"]["errin"], 1)
        self.assertEqual(payload["samples"]["network_metrics"]["dropout"], 4)

        self.assertEqual(payload["samples"]["internet_speed"]["state"], "ok")
        self.assertEqual(payload["samples"]["internet_speed"]["source"], "speedtest_cli")
        self.assertEqual(payload["samples"]["internet_speed"]["download_mbps"], 12.5)
        self.assertEqual(payload["samples"]["internet_speed"]["upload_mbps"], 5.0)
        self.assertEqual(payload["samples"]["internet_speed"]["latency_ms"], 23.6)


if __name__ == "__main__":
    unittest.main()

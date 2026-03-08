from __future__ import annotations

import os
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    def __init__(self, total_rate: _FakeRate | None = None) -> None:
        self.total_rate = total_rate


class _FakeStats:
    def __init__(self, total_rate: _FakeRate | None = None) -> None:
        self.net = _FakeNet(total_rate=total_rate)
        self.services = {}


class TestStackHealthSummaryApi(unittest.TestCase):
    def setUp(self) -> None:
        self.old_local = os.environ.get("SYNTHIA_LOCAL_NETWORK_CHECK_HOST")
        self.old_internet = os.environ.get("SYNTHIA_INTERNET_CHECK_HOST")
        self.old_download = os.environ.get("SYNTHIA_SPEEDTEST_DOWNLOAD_URL")
        self.old_upload = os.environ.get("SYNTHIA_SPEEDTEST_UPLOAD_URL")

        os.environ["SYNTHIA_LOCAL_NETWORK_CHECK_HOST"] = ""
        os.environ["SYNTHIA_INTERNET_CHECK_HOST"] = ""
        os.environ["SYNTHIA_SPEEDTEST_DOWNLOAD_URL"] = ""
        os.environ["SYNTHIA_SPEEDTEST_UPLOAD_URL"] = ""

    def tearDown(self) -> None:
        if self.old_local is None:
            os.environ.pop("SYNTHIA_LOCAL_NETWORK_CHECK_HOST", None)
        else:
            os.environ["SYNTHIA_LOCAL_NETWORK_CHECK_HOST"] = self.old_local

        if self.old_internet is None:
            os.environ.pop("SYNTHIA_INTERNET_CHECK_HOST", None)
        else:
            os.environ["SYNTHIA_INTERNET_CHECK_HOST"] = self.old_internet

        if self.old_download is None:
            os.environ.pop("SYNTHIA_SPEEDTEST_DOWNLOAD_URL", None)
        else:
            os.environ["SYNTHIA_SPEEDTEST_DOWNLOAD_URL"] = self.old_download

        if self.old_upload is None:
            os.environ.pop("SYNTHIA_SPEEDTEST_UPLOAD_URL", None)
        else:
            os.environ["SYNTHIA_SPEEDTEST_UPLOAD_URL"] = self.old_upload

    def test_stack_summary_returns_dashboard_contract(self) -> None:
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
        self.assertEqual(payload["samples"]["internet_speed"]["state"], "not_configured")
        self.assertEqual(payload["samples"]["network_throughput"]["state"], "warming_up")

    def test_stack_summary_derives_passive_speed_when_active_probe_not_configured(self) -> None:
        app = FastAPI()
        app.include_router(build_stack_health_router(), prefix="/api/system")
        app.state.scheduler_engine = _FakeScheduler()
        app.state.mqtt_manager = _FakeMqtt()
        app.state.addon_registry = _FakeRegistry()
        app.state.latest_stats = _FakeStats(total_rate=_FakeRate(rx_Bps=1_250_000.0, tx_Bps=625_000.0))

        client = TestClient(app)
        res = client.get("/api/system/stack/summary")
        self.assertEqual(res.status_code, 200, res.text)

        payload = res.json()
        self.assertEqual(payload["samples"]["network_throughput"]["state"], "ok")
        self.assertEqual(payload["samples"]["network_throughput"]["rx_Bps"], 1250000.0)
        self.assertEqual(payload["samples"]["network_throughput"]["tx_Bps"], 625000.0)

        self.assertEqual(payload["samples"]["internet_speed"]["state"], "ok")
        self.assertEqual(payload["samples"]["internet_speed"]["source"], "passive_estimate")
        self.assertEqual(payload["samples"]["internet_speed"]["download_mbps"], 10.0)
        self.assertEqual(payload["samples"]["internet_speed"]["upload_mbps"], 5.0)


if __name__ == "__main__":
    unittest.main()

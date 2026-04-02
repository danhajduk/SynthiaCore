from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from subprocess import CompletedProcess

from app.system import stack_health
from app.system.mqtt.integration_models import MqttIntegrationState
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


class _FakeMqttRuntime:
    async def get_status(self):
        return type("S", (), {"healthy": True, "state": "running", "degraded_reason": None})()


class _FakeMqttStateStore:
    async def get_state(self):
        return MqttIntegrationState(
            requires_setup=True,
            setup_complete=True,
            setup_status="ready",
            authority_ready=True,
        )


class _FakeMqttStartupReconciler:
    def reconciliation_status(self) -> dict[str, object]:
        return {
            "last_reconcile_at": "2026-03-09T09:00:00Z",
            "last_reconcile_reason": "startup",
            "last_reconcile_status": "ok",
            "last_reconcile_error": None,
            "last_runtime_state": "running",
        }

    def bootstrap_status(self) -> dict[str, object]:
        return {
            "published": True,
            "attempts": 1,
            "successes": 1,
            "last_attempt_at": "2026-03-09T09:00:00Z",
            "last_success_at": "2026-03-09T09:00:00Z",
            "last_error": None,
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


class _FakeNodeRegistration:
    def __init__(self, node_type: str, trust_status: str) -> None:
        self.node_type = node_type
        self.trust_status = trust_status


class _FakeNodeRegistrationsStore:
    def __init__(self, items: list[_FakeNodeRegistration]) -> None:
        self._items = list(items)

    def list(self) -> list[_FakeNodeRegistration]:
        return list(self._items)


class TestStackHealthSummaryApi(unittest.TestCase):
    def setUp(self) -> None:
        self.old_local = os.environ.get("SYNTHIA_LOCAL_NETWORK_CHECK_HOST")
        self.old_internet = os.environ.get("SYNTHIA_INTERNET_CHECK_HOST")
        self.old_mqtt_host = os.environ.get("MQTT_HOST")
        self.old_backend_host = os.environ.get("SYNTHIA_BACKEND_HOST")
        self.old_backend_port = os.environ.get("SYNTHIA_BACKEND_PORT")
        self.old_speedtest_cli_bin = os.environ.get("SYNTHIA_SPEEDTEST_CLI_BIN")

        os.environ["SYNTHIA_LOCAL_NETWORK_CHECK_HOST"] = ""
        os.environ["SYNTHIA_INTERNET_CHECK_HOST"] = ""
        os.environ["MQTT_HOST"] = ""
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

        if self.old_mqtt_host is None:
            os.environ.pop("MQTT_HOST", None)
        else:
            os.environ["MQTT_HOST"] = self.old_mqtt_host

        if self.old_backend_host is None:
            os.environ.pop("SYNTHIA_BACKEND_HOST", None)
        else:
            os.environ["SYNTHIA_BACKEND_HOST"] = self.old_backend_host

        if self.old_backend_port is None:
            os.environ.pop("SYNTHIA_BACKEND_PORT", None)
        else:
            os.environ["SYNTHIA_BACKEND_PORT"] = self.old_backend_port

        if self.old_speedtest_cli_bin is None:
            os.environ.pop("SYNTHIA_SPEEDTEST_CLI_BIN", None)
        else:
            os.environ["SYNTHIA_SPEEDTEST_CLI_BIN"] = self.old_speedtest_cli_bin

        stack_health._sampler._speed_cache = None
        stack_health._sampler._connectivity_cache = None

    def test_stack_summary_returns_dashboard_contract(self) -> None:
        app = FastAPI()
        app.include_router(build_stack_health_router(), prefix="/api/system")
        app.state.scheduler_engine = _FakeScheduler()
        app.state.mqtt_manager = _FakeMqtt()
        app.state.mqtt_runtime_boundary = _FakeMqttRuntime()
        app.state.mqtt_integration_state_store = _FakeMqttStateStore()
        app.state.mqtt_startup_reconciler = _FakeMqttStartupReconciler()
        app.state.addon_registry = _FakeRegistry()
        app.state.node_registrations_store = _FakeNodeRegistrationsStore(
            [_FakeNodeRegistration(node_type="ai-node", trust_status="trusted")]
        )
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
        self.assertTrue(payload["subsystems"]["mqtt"]["infrastructure"]["broker_runtime"]["healthy"])
        self.assertTrue(payload["subsystems"]["mqtt"]["infrastructure"]["authority"]["healthy"])
        self.assertEqual(payload["subsystems"]["mqtt"]["infrastructure"]["reconciliation"]["status"], "ok")
        self.assertTrue(payload["subsystems"]["mqtt"]["infrastructure"]["bootstrap_publish"]["published"])
        self.assertEqual(payload["subsystems"]["scheduler"]["state"], "running")
        self.assertEqual(payload["subsystems"]["workers"]["active_count"], 2)
        self.assertEqual(payload["subsystems"]["addons"]["installed_count"], 2)
        self.assertEqual(payload["subsystems"]["addons"]["unhealthy_count"], 1)
        self.assertEqual(payload["subsystems"]["ai"]["state"], "connected")
        self.assertEqual(payload["subsystems"]["ai"]["trusted_nodes"], 1)

        self.assertEqual(payload["connectivity"]["network"]["state"], "not_configured")
        self.assertEqual(payload["connectivity"]["internet"]["state"], "not_configured")
        self.assertEqual(payload["samples"]["internet_speed"]["state"], "unavailable")
        self.assertEqual(payload["samples"]["network_throughput"]["state"], "warming_up")
        self.assertEqual(payload["samples"]["network_metrics"]["state"], "ok")

    def test_stack_summary_accepts_legacy_ai_node_type_label(self) -> None:
        app = FastAPI()
        app.include_router(build_stack_health_router(), prefix="/api/system")
        app.state.scheduler_engine = _FakeScheduler()
        app.state.mqtt_manager = _FakeMqtt()
        app.state.mqtt_runtime_boundary = _FakeMqttRuntime()
        app.state.mqtt_integration_state_store = _FakeMqttStateStore()
        app.state.mqtt_startup_reconciler = _FakeMqttStartupReconciler()
        app.state.addon_registry = _FakeRegistry()
        app.state.node_registrations_store = _FakeNodeRegistrationsStore(
            [_FakeNodeRegistration(node_type="ai", trust_status="trusted")]
        )
        app.state.latest_stats = _FakeStats()

        client = TestClient(app)
        res = client.get("/api/system/stack/summary")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()

        self.assertEqual(payload["subsystems"]["ai"]["state"], "connected")
        self.assertEqual(payload["subsystems"]["ai"]["trusted_nodes"], 1)
        self.assertEqual(payload["subsystems"]["ai"]["total_nodes"], 1)

    def test_no_workers_active_reason_does_not_degrade_overall_status(self) -> None:
        payload = stack_health._derive_overall_status(
            {
                "subsystems": {
                    "core": {"state": "healthy"},
                    "supervisor": {"state": "healthy"},
                    "workers": {"state": "idle"},
                    "mqtt": {"state": "connected"},
                    "scheduler": {"state": "running"},
                    "addons": {"unhealthy_count": 0},
                },
                "connectivity": {
                    "network": {"state": "reachable"},
                    "internet": {"state": "reachable"},
                },
            }
        )
        self.assertEqual(payload["overall"], "ok")
        self.assertIn("No workers active", payload["reasons"])

    def test_ai_offline_degrades_overall_status(self) -> None:
        payload = stack_health._derive_overall_status(
            {
                "subsystems": {
                    "core": {"state": "healthy"},
                    "supervisor": {"state": "healthy"},
                    "ai": {"state": "offline"},
                    "workers": {"state": "active"},
                    "mqtt": {"state": "connected"},
                    "scheduler": {"state": "running"},
                    "addons": {"unhealthy_count": 0},
                },
                "connectivity": {
                    "network": {"state": "reachable"},
                    "internet": {"state": "reachable"},
                },
            }
        )
        self.assertEqual(payload["overall"], "degraded")
        self.assertIn("AI offline", payload["reasons"])

    def test_stale_mqtt_reconcile_does_not_degrade_when_runtime_is_healthy(self) -> None:
        payload = stack_health._derive_overall_status(
            {
                "subsystems": {
                    "core": {"state": "healthy"},
                    "supervisor": {"state": "healthy"},
                    "workers": {"state": "active"},
                    "mqtt": {
                        "state": "connected",
                        "infrastructure": {
                            "broker_runtime": {"healthy": True, "state": "running"},
                            "authority": {
                                "healthy": True,
                                "authority_ready": True,
                                "setup_ready": True,
                                "setup_status": "ready",
                            },
                            "reconciliation": {"status": "degraded"},
                            "bootstrap_publish": {"published": True, "attempts": 1},
                        },
                    },
                    "scheduler": {"state": "running"},
                    "addons": {"unhealthy_count": 0},
                },
                "connectivity": {
                    "network": {"state": "reachable"},
                    "internet": {"state": "reachable"},
                },
            }
        )
        self.assertEqual(payload["overall"], "ok")
        self.assertNotIn("MQTT reconciliation degraded", payload["reasons"])

    @patch("app.system.stack_health.subprocess.run")
    def test_stack_summary_uses_cached_speed_only(self, mock_run) -> None:
        stack_health._sampler._speed_cache = {
            "ts": 1_000.0,
            "payload": {
                "state": "ok",
                "source": "speedtest_cli",
                "download_mbps": 12.5,
                "upload_mbps": 5.0,
                "latency_ms": 23.6,
                "sampled_at": "2026-03-07T12:00:00+00:00",
                "age_s": 0,
            },
        }
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
        mock_run.assert_not_called()

    def test_stack_summary_falls_back_to_passive_speed_estimate(self) -> None:
        stack_health._sampler._speed_cache = {
            "ts": 1_000.0,
            "payload": {
                "state": "unavailable",
                "source": "speedtest_cli",
                "download_mbps": None,
                "upload_mbps": None,
                "latency_ms": None,
                "sampled_at": "2026-03-07T12:00:00+00:00",
                "age_s": 0,
            },
        }

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
        self.assertEqual(payload["samples"]["internet_speed"]["state"], "ok")
        self.assertEqual(payload["samples"]["internet_speed"]["source"], "passive_estimate")
        self.assertEqual(payload["samples"]["internet_speed"]["download_mbps"], 10.0)
        self.assertEqual(payload["samples"]["internet_speed"]["upload_mbps"], 5.0)
        self.assertIsNone(payload["samples"]["internet_speed"]["latency_ms"])

    @patch("app.system.stack_health.shutil.which")
    @patch("app.system.stack_health.subprocess.run")
    def test_sample_speed_falls_back_to_python_module_speedtest(self, mock_run, mock_which) -> None:
        mock_which.return_value = None
        mock_run.side_effect = [
            FileNotFoundError("speedtest-cli"),
            CompletedProcess(
                args=["python", "-m", "speedtest"],
                returncode=0,
                stdout='{"download": 30000000, "upload": 9000000, "ping": 18.4}',
                stderr="",
            ),
        ]

        payload = stack_health._sample_speed()
        self.assertEqual(payload["state"], "ok")
        self.assertEqual(payload["source"], "speedtest_cli")
        self.assertEqual(payload["download_mbps"], 30.0)
        self.assertEqual(payload["upload_mbps"], 9.0)
        self.assertEqual(payload["latency_ms"], 18.4)

    @patch("app.system.stack_health.shutil.which")
    @patch("app.system.stack_health.subprocess.run")
    def test_sample_speed_parses_ookla_speedtest_json(self, mock_run, mock_which) -> None:
        mock_which.return_value = None
        os.environ["SYNTHIA_SPEEDTEST_CLI_BIN"] = "speedtest"
        mock_run.return_value = CompletedProcess(
            args=["speedtest"],
            returncode=0,
            stdout='{"download":{"bandwidth":1500000},"upload":{"bandwidth":500000},"ping":{"latency":21.7}}',
            stderr="",
        )

        payload = stack_health._sample_speed()
        self.assertEqual(payload["state"], "ok")
        self.assertEqual(payload["source"], "speedtest_ookla")
        self.assertEqual(payload["download_mbps"], 12.0)
        self.assertEqual(payload["upload_mbps"], 4.0)
        self.assertEqual(payload["latency_ms"], 21.7)

    @patch("app.system.stack_health._tcp_reachable", return_value=True)
    def test_stack_summary_uses_mqtt_host_for_network_check_when_local_host_missing(self, mock_reachable) -> None:
        os.environ["SYNTHIA_INTERNET_CHECK_HOST"] = ""
        os.environ["SYNTHIA_LOCAL_NETWORK_CHECK_HOST"] = ""
        os.environ["MQTT_HOST"] = "10.0.0.100"

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
        self.assertEqual(payload["connectivity"]["network"]["state"], "reachable")
        self.assertEqual(payload["connectivity"]["internet"]["state"], "not_configured")
        self.assertEqual(mock_reachable.call_count, 1)
        self.assertEqual(mock_reachable.call_args.args[0], "10.0.0.100")

    @patch("app.system.stack_health._tcp_reachable", return_value=True)
    def test_stack_summary_uses_backend_host_for_network_check_when_local_and_mqtt_missing(self, mock_reachable) -> None:
        os.environ["SYNTHIA_INTERNET_CHECK_HOST"] = ""
        os.environ["SYNTHIA_LOCAL_NETWORK_CHECK_HOST"] = ""
        os.environ["MQTT_HOST"] = ""
        os.environ["SYNTHIA_BACKEND_HOST"] = "10.0.0.100"
        os.environ["SYNTHIA_BACKEND_PORT"] = "9001"

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
        self.assertEqual(payload["connectivity"]["network"]["state"], "reachable")
        self.assertEqual(payload["connectivity"]["internet"]["state"], "not_configured")
        self.assertEqual(mock_reachable.call_count, 1)
        self.assertEqual(mock_reachable.call_args.args[0], "10.0.0.100")
        self.assertEqual(mock_reachable.call_args.args[1], 9001)


if __name__ == "__main__":
    unittest.main()

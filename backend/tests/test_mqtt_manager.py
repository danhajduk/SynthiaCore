import asyncio
import json
import os
import tempfile
import unittest

import paho.mqtt.client as mqtt
from paho.mqtt.reasoncodes import ReasonCode

from app.system.mqtt.manager import MQTT_SUBSCRIPTIONS, MqttConfig, MqttManager


class _FakeSettingsStore:
    async def get(self, key: str):
        return None


class _MapSettingsStore:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    async def get(self, key: str):
        return self.values.get(key)


class _FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.registered: dict[str, object] = {}

    def update_from_mqtt_announce(self, addon_id: str, payload: dict) -> None:
        self.calls.append(("announce", addon_id, payload))

    def update_from_mqtt_health(self, addon_id: str, payload: dict) -> None:
        self.calls.append(("health", addon_id, payload))


class _FakeServiceCatalogStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def upsert_catalog(self, service_name: str, payload: dict) -> None:
        self.calls.append((service_name, payload))


class _FakeInstallSessionsStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def mark_discovered(self, addon_id: str) -> int:
        self.calls.append(addon_id)
        return 1


class _Msg:
    def __init__(self, topic: str, payload: dict | int | str, *, retain: bool = False) -> None:
        self.topic = topic
        self.retain = bool(retain)
        if isinstance(payload, (dict, list)):
            self.payload = json.dumps(payload).encode("utf-8")
        else:
            self.payload = str(payload).encode("utf-8")


class _PublishResult:
    def __init__(self, rc: int = 0) -> None:
        self.rc = rc


class _FakeClient:
    def __init__(self) -> None:
        self.subscribed: list[tuple[str, int]] = []
        self.published: list[tuple[str, dict, int, bool]] = []

    def subscribe(self, topic: str, qos: int = 0):
        self.subscribed.append((topic, qos))
        return (0, 1)

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False):
        self.published.append((topic, json.loads(payload), qos, retain))
        return _PublishResult(rc=0)


class TestMqttManager(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_listener_is_noop(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=False,
        )
        await manager.start()
        status = await manager.status()
        self.assertFalse(status["enabled"])
        self.assertFalse(status["connected"])
        self.assertEqual(status["last_error"], "mqtt_disabled")
        self.assertEqual(status["connection_count"], 0)
        self.assertEqual(status["auth_failures"], 0)
        self.assertEqual(status["reconnect_spikes"], 0)

    async def test_dispatches_addon_announce_and_health(self) -> None:
        registry = _FakeRegistry()
        sessions = _FakeInstallSessionsStore()
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=registry,
            service_catalog_store=_FakeServiceCatalogStore(),
            install_sessions_store=sessions,
            enabled=True,
        )
        manager._loop = asyncio.get_running_loop()

        manager._on_message(None, None, _Msg("synthia/addons/mqtt/announce", {"base_url": "http://127.0.0.1:9100"}))
        manager._on_message(None, None, _Msg("synthia/addons/mqtt/health", {"status": "ok"}))
        await asyncio.sleep(0.02)

        self.assertEqual(len(registry.calls), 2)
        self.assertEqual(registry.calls[0][0], "announce")
        self.assertEqual(registry.calls[0][1], "mqtt")
        self.assertEqual(registry.calls[1][0], "health")
        self.assertEqual(registry.calls[1][1], "mqtt")
        self.assertEqual(sessions.calls, ["mqtt"])
        runtime = await manager.principal_connection_states()
        self.assertTrue(runtime["addon:mqtt"]["connected"])
        self.assertGreaterEqual(int(runtime["addon:mqtt"]["session_count"]), 1)

    async def test_on_connect_publishes_retained_core_info(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._config = MqttConfig(
            mode="external",
            host="10.0.0.100",
            port=1883,
            username="broker-user",
            password=None,
            keepalive_s=30,
            tls_enabled=False,
            client_id="synthia-core",
        )
        client = _FakeClient()

        manager._on_connect(client, None, None, 0)

        self.assertTrue(manager._connected)
        self.assertEqual(client.subscribed, MQTT_SUBSCRIPTIONS)
        self.assertEqual(len(client.published), 1)
        topic, payload, qos, retain = client.published[0]
        self.assertEqual(topic, "synthia/core/mqtt/info")
        self.assertEqual(qos, 1)
        self.assertTrue(retain)
        self.assertEqual(payload["source"], "synthia-core")
        self.assertEqual(payload["type"], "core-mqtt-info")
        self.assertTrue(payload["heartbeat_ts"].endswith("Z"))
        self.assertEqual(payload["broker"]["mode"], "external")
        self.assertEqual(payload["broker"]["host"], "10.0.0.100")
        self.assertEqual(payload["broker"]["port"], 1883)
        self.assertFalse(payload["broker"]["tls_enabled"])
        self.assertTrue(payload["broker"]["username_set"])
        runtime = await manager.principal_connection_states()
        self.assertTrue(runtime["core.runtime"]["connected"])
        sessions = await manager.runtime_sessions()
        self.assertTrue(any(str(item.get("principal_id")) == "core.runtime" for item in sessions["items"]))

    async def test_on_connect_failure_does_not_publish_core_info(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._config = MqttConfig(
            mode="external",
            host="10.0.0.100",
            port=1883,
            username=None,
            password=None,
            keepalive_s=30,
            tls_enabled=False,
            client_id="synthia-core",
        )
        client = _FakeClient()

        manager._on_connect(client, None, None, 5)

        self.assertFalse(manager._connected)
        self.assertEqual(manager._last_error, "connect_rc:5")
        self.assertEqual(manager._auth_failures, 1)
        self.assertEqual(client.subscribed, [])
        self.assertEqual(client.published, [])

    async def test_runtime_disconnect_marks_core_runtime_disconnected(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._config = MqttConfig(
            mode="external",
            host="10.0.0.100",
            port=1883,
            username=None,
            password=None,
            keepalive_s=30,
            tls_enabled=False,
            client_id="synthia-core",
        )
        client = _FakeClient()
        manager._on_connect(client, None, None, 0)
        manager._on_disconnect(client, None, None, 0)
        runtime = await manager.principal_connection_states()
        self.assertIn("core.runtime", runtime)
        self.assertFalse(runtime["core.runtime"]["connected"])

    async def test_parses_sys_client_topics_into_runtime_sessions_payload(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._loop = asyncio.get_running_loop()
        manager._on_message(None, None, _Msg("$SYS/broker/clients/connected", 7))
        manager._on_message(None, None, _Msg("$SYS/broker/clients/disconnected", 3))
        sessions = await manager.runtime_sessions()
        self.assertEqual(sessions["broker_clients"]["connected"], 7)
        self.assertEqual(sessions["broker_clients"]["disconnected"], 3)

    async def test_broker_health_metrics_from_sys_topics(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._loop = asyncio.get_running_loop()
        manager._on_message(None, None, _Msg("$SYS/broker/uptime", "17 seconds"))
        manager._on_message(None, None, _Msg("$SYS/broker/clients/connected", 4))
        manager._on_message(None, None, _Msg("$SYS/broker/messages/sent", 120))
        manager._on_message(None, None, _Msg("$SYS/broker/messages/received", 80))
        manager._on_message(None, None, _Msg("$SYS/broker/publish/messages/dropped", 2))
        manager._on_message(None, None, _Msg("$SYS/broker/retained messages/count", 5))
        metrics = await manager.broker_health_metrics()
        self.assertEqual(metrics["broker_uptime"], "17 seconds")
        self.assertEqual(metrics["connected_clients"], 4)
        self.assertEqual(metrics["dropped_messages"], 2)
        self.assertEqual(metrics["retained_messages"], 5)

    async def test_principal_traffic_metrics_tracks_addon_topics(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._loop = asyncio.get_running_loop()
        manager._on_message(None, None, _Msg("synthia/addons/mqtt/announce", {"ok": True}))
        manager._on_message(None, None, _Msg("synthia/addons/mqtt/health", {"status": "ok"}))
        metrics = await manager.principal_traffic_metrics()
        self.assertIn("addon:mqtt", metrics)
        self.assertGreater(float(metrics["addon:mqtt"]["messages_per_second"]), 0.0)
        self.assertGreaterEqual(int(metrics["addon:mqtt"]["topic_count"]), 1)

    async def test_topic_activity_tracks_runtime_and_retained_sources(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._loop = asyncio.get_running_loop()
        manager._on_message(None, None, _Msg("external/frigate/events", {"ok": True}, retain=True))
        manager._on_message(None, None, _Msg("external/frigate/events", {"ok": False}, retain=False))
        topics = await manager.topic_activity(limit=100)
        self.assertTrue(topics["ok"])
        self.assertEqual(len(topics["items"]), 1)
        item = topics["items"][0]
        self.assertEqual(item["topic"], "external/frigate/events")
        self.assertEqual(int(item["message_count"]), 2)
        self.assertTrue(bool(item["retained_seen"]))
        self.assertIn("runtime_messages", item["sources"])
        self.assertIn("retained", item["sources"])

    async def test_runtime_stats_history_tracks_message_rate_clients_and_errors(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._loop = asyncio.get_running_loop()
        manager._on_message(None, None, _Msg("$SYS/broker/clients/connected", 4))
        manager._on_message(None, None, _Msg("$SYS/broker/messages/sent", 100))
        manager._on_message(None, None, _Msg("$SYS/broker/messages/received", 120))
        manager._on_disconnect(None, None, None, 5)
        history = await manager.runtime_stats_history(hours=24, limit=100)
        self.assertTrue(history["ok"])
        self.assertTrue(history["items"])
        sample = history["items"][-1]
        self.assertIn("timestamp", sample)
        self.assertIn("messages_per_second", sample)
        self.assertIn("connected_clients", sample)
        self.assertIn("errors", sample)

    async def test_on_connect_accepts_reason_code_object(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._config = MqttConfig(
            mode="external",
            host="10.0.0.100",
            port=1883,
            username=None,
            password=None,
            keepalive_s=30,
            tls_enabled=False,
            client_id="synthia-core",
        )
        client = _FakeClient()
        rc = ReasonCode(mqtt.PacketTypes.CONNACK, identifier=0)

        manager._on_connect(client, None, None, rc)

        self.assertTrue(manager._connected)
        self.assertEqual(client.subscribed, MQTT_SUBSCRIPTIONS)

    async def test_load_config_local_ignores_stale_auth_settings(self) -> None:
        manager = MqttManager(
            settings_store=_MapSettingsStore(
                {
                    "mqtt.mode": "local",
                    "mqtt.local.host": "10.0.0.100",
                    "mqtt.local.port": 1883,
                    "mqtt.local.username": "admin",
                    "mqtt.local.password": "bad",
                    "mqtt.local.tls_enabled": True,
                    "mqtt.client_id": "synthia-core",
                }
            ),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        old = os.environ.get("MQTT_CREDENTIAL_STORE_PATH")
        os.environ["MQTT_CREDENTIAL_STORE_PATH"] = "/tmp/does-not-exist-mqtt-credentials.json"
        try:
            cfg = await manager._load_config()
        finally:
            if old is None:
                del os.environ["MQTT_CREDENTIAL_STORE_PATH"]
            else:
                os.environ["MQTT_CREDENTIAL_STORE_PATH"] = old
        self.assertEqual(cfg.mode, "local")
        self.assertEqual(cfg.host, "127.0.0.1")
        self.assertEqual(cfg.port, 1883)
        self.assertEqual(cfg.username, "admin")
        self.assertEqual(cfg.password, "bad")
        self.assertFalse(cfg.tls_enabled)

    async def test_load_config_local_prefers_runtime_credential_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cred_path = os.path.join(tmp, "mqtt_credentials.json")
            with open(cred_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "credentials": {
                            "addon:mqtt": {
                                "username": "sx_mqtt",
                                "password": "runtime-secret",
                            }
                        }
                    },
                    handle,
                )
            manager = MqttManager(
                settings_store=_MapSettingsStore(
                    {
                        "mqtt.mode": "local",
                        "mqtt.local.host": "10.0.0.100",
                        "mqtt.local.port": 1883,
                        "mqtt.local.username": "admin",
                        "mqtt.local.password": "stale-password",
                        "mqtt.local.tls_enabled": True,
                        "mqtt.client_id": "synthia-core",
                    }
                ),
                registry=_FakeRegistry(),
                service_catalog_store=_FakeServiceCatalogStore(),
                enabled=True,
            )
            old = os.environ.get("MQTT_CREDENTIAL_STORE_PATH")
            os.environ["MQTT_CREDENTIAL_STORE_PATH"] = cred_path
            try:
                cfg = await manager._load_config()
            finally:
                if old is None:
                    del os.environ["MQTT_CREDENTIAL_STORE_PATH"]
                else:
                    os.environ["MQTT_CREDENTIAL_STORE_PATH"] = old
            self.assertEqual(cfg.mode, "local")
            self.assertEqual(cfg.username, "sx_mqtt")
            self.assertEqual(cfg.password, "runtime-secret")

    async def test_load_config_external_keeps_auth_settings(self) -> None:
        manager = MqttManager(
            settings_store=_MapSettingsStore(
                {
                    "mqtt.mode": "external",
                    "mqtt.external.host": "10.0.0.200",
                    "mqtt.external.port": 2883,
                    "mqtt.external.username": "broker-user",
                    "mqtt.external.password": "broker-pass",
                    "mqtt.external.tls_enabled": True,
                    "mqtt.client_id": "synthia-core",
                }
            ),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        cfg = await manager._load_config()
        self.assertEqual(cfg.mode, "external")
        self.assertEqual(cfg.host, "10.0.0.200")
        self.assertEqual(cfg.port, 2883)
        self.assertEqual(cfg.username, "broker-user")
        self.assertEqual(cfg.password, "broker-pass")
        self.assertTrue(cfg.tls_enabled)


if __name__ == "__main__":
    unittest.main()

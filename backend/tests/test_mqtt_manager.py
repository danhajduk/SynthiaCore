import asyncio
import json
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
    def __init__(self, topic: str, payload: dict) -> None:
        self.topic = topic
        self.payload = json.dumps(payload).encode("utf-8")


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
            password="secret-password",
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
        cfg = await manager._load_config()
        self.assertEqual(cfg.mode, "local")
        self.assertEqual(cfg.host, "127.0.0.1")
        self.assertEqual(cfg.port, 1883)
        self.assertIsNone(cfg.username)
        self.assertIsNone(cfg.password)
        self.assertFalse(cfg.tls_enabled)

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

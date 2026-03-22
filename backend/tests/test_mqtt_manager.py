import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

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

        manager._on_message(None, None, _Msg("hexe/addons/mqtt/announce", {"base_url": "http://127.0.0.1:9100"}))
        manager._on_message(None, None, _Msg("hexe/addons/mqtt/health", {"status": "ok"}))
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

    async def test_message_listener_receives_matching_runtime_notifications(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._loop = asyncio.get_running_loop()
        seen: list[tuple[str, dict, bool]] = []

        async def _listener(topic: str, payload: dict, retained: bool) -> None:
            seen.append((topic, payload, retained))

        listener_id = manager.register_message_listener(
            topic_filter="hexe/notify/internal/popup",
            callback=_listener,
        )

        manager._on_message(None, None, _Msg("hexe/notify/internal/popup", {"content": {"title": "hi"}}, retain=False))
        manager._on_message(None, None, _Msg("hexe/notify/internal/event", {"event": {"event_type": "skip"}}, retain=False))
        await asyncio.sleep(0.02)

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "hexe/notify/internal/popup")
        self.assertFalse(seen[0][2])
        self.assertTrue(manager.unregister_message_listener(listener_id))

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
        self.assertEqual(topic, "hexe/core/mqtt/info")
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
        self.assertIn(("#", 0), client.subscribed)

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

    async def test_tracks_node_lifecycle_and_health_topics(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._loop = asyncio.get_running_loop()

        manager._on_message(
            None,
            None,
            _Msg(
                "hexe/nodes/node-123/lifecycle",
                {"node_id": "node-123", "lifecycle_state": "ready", "message": "boot complete"},
                retain=True,
            ),
        )
        manager._on_message(
            None,
            None,
            _Msg(
                "hexe/nodes/node-123/status",
                {"node_id": "node-123", "health_status": "healthy", "summary": "all systems nominal"},
                retain=True,
            ),
        )

        snapshot = await manager.node_runtime_snapshot("node-123")
        assert snapshot is not None
        self.assertEqual(snapshot["node_id"], "node-123")
        self.assertEqual(snapshot["reported_lifecycle_state"], "ready")
        self.assertEqual(snapshot["reported_health_status"], "healthy")
        self.assertEqual(snapshot["lifecycle"]["topic"], "hexe/nodes/node-123/lifecycle")
        self.assertTrue(bool(snapshot["lifecycle"]["retained"]))
        self.assertEqual(snapshot["status"]["topic"], "hexe/nodes/node-123/status")
        self.assertTrue(bool(snapshot["status"]["retained"]))

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

    async def test_broker_message_rate_updates_from_runtime_traffic(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._loop = asyncio.get_running_loop()
        manager._on_message(None, None, _Msg("frigate/events", {"ok": True}))
        await asyncio.sleep(1.05)
        manager._on_message(None, None, _Msg("frigate/events", {"ok": True}))
        metrics = await manager.broker_health_metrics()
        self.assertIsNotNone(metrics["message_rate"])
        self.assertGreater(float(metrics["message_rate"]), 0.0)

    async def test_principal_traffic_metrics_tracks_addon_topics(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._loop = asyncio.get_running_loop()
        manager._on_message(None, None, _Msg("hexe/addons/mqtt/announce", {"ok": True}))
        manager._on_message(None, None, _Msg("hexe/addons/mqtt/health", {"status": "ok"}))
        metrics = await manager.principal_traffic_metrics()
        self.assertIn("addon:mqtt", metrics)
        self.assertGreater(float(metrics["addon:mqtt"]["messages_per_second"]), 0.0)
        self.assertGreaterEqual(int(metrics["addon:mqtt"]["topic_count"]), 1)

    async def test_principal_traffic_metrics_prefers_generic_topic_prefix_over_broad_wildcards(self) -> None:
        old_state_path = os.environ.get("MQTT_INTEGRATION_STATE_PATH")
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "mqtt_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "principals": {
                            "user:frigate": {
                                "principal_type": "generic_user",
                                "status": "active",
                                "topic_prefix": "external/frigate",
                                "publish_topics": ["#"],
                                "subscribe_topics": ["#"],
                            },
                            "user:homeassistant": {
                                "principal_type": "generic_user",
                                "status": "active",
                                "topic_prefix": "external/homeassistant",
                                "publish_topics": ["#"],
                                "subscribe_topics": ["#"],
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            os.environ["MQTT_INTEGRATION_STATE_PATH"] = str(state_path)
            manager = MqttManager(
                settings_store=_FakeSettingsStore(),
                registry=_FakeRegistry(),
                service_catalog_store=_FakeServiceCatalogStore(),
                enabled=True,
            )
            manager._loop = asyncio.get_running_loop()

            manager._on_message(None, None, _Msg("external/frigate/events", {"ok": True}))

            metrics = await manager.principal_traffic_metrics()
            self.assertIn("user:frigate", metrics)
            self.assertNotIn("user:homeassistant", metrics)
        if old_state_path is None:
            os.environ.pop("MQTT_INTEGRATION_STATE_PATH", None)
        else:
            os.environ["MQTT_INTEGRATION_STATE_PATH"] = old_state_path

    async def test_principal_traffic_metrics_uses_topic_head_when_broad_scopes_are_ambiguous(self) -> None:
        old_state_path = os.environ.get("MQTT_INTEGRATION_STATE_PATH")
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "mqtt_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "principals": {
                            "user:frigate": {
                                "principal_type": "generic_user",
                                "status": "active",
                                "topic_prefix": "external/frigate",
                                "publish_topics": ["#"],
                                "subscribe_topics": ["#"],
                            },
                            "user:homeassistant": {
                                "principal_type": "generic_user",
                                "status": "active",
                                "topic_prefix": "external/homeassistant",
                                "publish_topics": ["#"],
                                "subscribe_topics": ["#"],
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            os.environ["MQTT_INTEGRATION_STATE_PATH"] = str(state_path)
            manager = MqttManager(
                settings_store=_FakeSettingsStore(),
                registry=_FakeRegistry(),
                service_catalog_store=_FakeServiceCatalogStore(),
                enabled=True,
            )
            manager._loop = asyncio.get_running_loop()

            manager._on_message(None, None, _Msg("frigate/events", {"ok": True}))

            metrics = await manager.principal_traffic_metrics()
            self.assertIn("user:frigate", metrics)
            self.assertNotIn("user:homeassistant", metrics)
        if old_state_path is None:
            os.environ.pop("MQTT_INTEGRATION_STATE_PATH", None)
        else:
            os.environ["MQTT_INTEGRATION_STATE_PATH"] = old_state_path

    async def test_topic_activity_tracks_runtime_and_retained_sources(self) -> None:
        old_state_path = os.environ.get("MQTT_INTEGRATION_STATE_PATH")
        os.environ["MQTT_INTEGRATION_STATE_PATH"] = "/tmp/non-existent-mqtt-state-for-test.json"
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        try:
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
            runtime = await manager.principal_connection_states()
            self.assertIn("user:external", runtime)
            self.assertTrue(runtime["user:external"]["connected"])
        finally:
            if old_state_path is None:
                del os.environ["MQTT_INTEGRATION_STATE_PATH"]
            else:
                os.environ["MQTT_INTEGRATION_STATE_PATH"] = old_state_path

    async def test_generic_topic_activity_marks_generic_principal_connected(self) -> None:
        old_state_path = os.environ.get("MQTT_INTEGRATION_STATE_PATH")
        os.environ["MQTT_INTEGRATION_STATE_PATH"] = "/tmp/non-existent-mqtt-state-for-test.json"
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        try:
            manager._loop = asyncio.get_running_loop()
            manager._on_message(None, None, _Msg("frigate/events", {"ok": True}, retain=False))
            runtime = await manager.principal_connection_states()
            self.assertIn("user:frigate", runtime)
            self.assertTrue(runtime["user:frigate"]["connected"])
            sessions = await manager.runtime_sessions()
            by_client = {str(item["client_id"]): item for item in sessions["items"]}
            self.assertIn("frigate", by_client)
            self.assertEqual(by_client["frigate"]["principal_id"], "user:frigate")
        finally:
            if old_state_path is None:
                del os.environ["MQTT_INTEGRATION_STATE_PATH"]
            else:
                os.environ["MQTT_INTEGRATION_STATE_PATH"] = old_state_path

    async def test_generic_topic_activity_maps_to_matching_user_scope_for_all_users(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "mqtt_integration_state.json")
            with open(state_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "principals": {
                            "user:frigate": {
                                "principal_id": "user:frigate",
                                "principal_type": "generic_user",
                                "status": "active",
                                "publish_topics": ["frigate/#"],
                                "subscribe_topics": [],
                            },
                            "user:homeassistant": {
                                "principal_id": "user:homeassistant",
                                "principal_type": "generic_user",
                                "status": "active",
                                "publish_topics": ["external/homeassistant/#"],
                                "subscribe_topics": [],
                            },
                        }
                    },
                    handle,
                )
            old = os.environ.get("MQTT_INTEGRATION_STATE_PATH")
            os.environ["MQTT_INTEGRATION_STATE_PATH"] = state_path
            try:
                manager = MqttManager(
                    settings_store=_FakeSettingsStore(),
                    registry=_FakeRegistry(),
                    service_catalog_store=_FakeServiceCatalogStore(),
                    enabled=True,
                )
                manager._loop = asyncio.get_running_loop()
                manager._on_message(None, None, _Msg("external/homeassistant/events", {"ok": True}, retain=False))
                runtime = await manager.principal_connection_states()
                self.assertIn("user:homeassistant", runtime)
                self.assertTrue(runtime["user:homeassistant"]["connected"])
                self.assertNotIn("user:external", runtime)
            finally:
                if old is None:
                    del os.environ["MQTT_INTEGRATION_STATE_PATH"]
                else:
                    os.environ["MQTT_INTEGRATION_STATE_PATH"] = old

    async def test_generic_topic_activity_ignores_wildcard_only_scopes_and_uses_topic_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "mqtt_integration_state.json")
            with open(state_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "principals": {
                            "user:frigate": {
                                "principal_id": "user:frigate",
                                "principal_type": "generic_user",
                                "status": "active",
                                "topic_prefix": "external/frigate",
                                "publish_topics": ["#"],
                                "subscribe_topics": ["#"],
                            },
                            "user:homeassistant": {
                                "principal_id": "user:homeassistant",
                                "principal_type": "generic_user",
                                "status": "active",
                                "topic_prefix": "external/homeassistant",
                                "publish_topics": ["#"],
                                "subscribe_topics": ["#"],
                            },
                        }
                    },
                    handle,
                )
            old = os.environ.get("MQTT_INTEGRATION_STATE_PATH")
            os.environ["MQTT_INTEGRATION_STATE_PATH"] = state_path
            try:
                manager = MqttManager(
                    settings_store=_FakeSettingsStore(),
                    registry=_FakeRegistry(),
                    service_catalog_store=_FakeServiceCatalogStore(),
                    enabled=True,
                )
                manager._loop = asyncio.get_running_loop()
                manager._on_message(None, None, _Msg("external/frigate/events", {"ok": True}, retain=False))
                manager._on_message(None, None, _Msg("external/homeassistant/events", {"ok": True}, retain=False))
                runtime = await manager.principal_connection_states()
                self.assertTrue(runtime["user:frigate"]["connected"])
                self.assertTrue(runtime["user:homeassistant"]["connected"])
            finally:
                if old is None:
                    del os.environ["MQTT_INTEGRATION_STATE_PATH"]
                else:
                    os.environ["MQTT_INTEGRATION_STATE_PATH"] = old

    async def test_addon_and_core_topic_activity_maps_to_principal_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "mqtt_integration_state.json")
            with open(state_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "principals": {
                            "addon:vision": {
                                "principal_id": "addon:vision",
                                "principal_type": "synthia_addon",
                                "status": "active",
                                "publish_topics": ["hexe/addons/vision/state/#"],
                                "subscribe_topics": ["hexe/addons/vision/command/#"],
                            },
                            "core.scheduler": {
                                "principal_id": "core.scheduler",
                                "principal_type": "system",
                                "status": "active",
                                "publish_topics": ["hexe/scheduler/heartbeat"],
                                "subscribe_topics": [],
                            },
                        }
                    },
                    handle,
                )
            old = os.environ.get("MQTT_INTEGRATION_STATE_PATH")
            os.environ["MQTT_INTEGRATION_STATE_PATH"] = state_path
            try:
                manager = MqttManager(
                    settings_store=_FakeSettingsStore(),
                    registry=_FakeRegistry(),
                    service_catalog_store=_FakeServiceCatalogStore(),
                    enabled=True,
                )
                manager._loop = asyncio.get_running_loop()
                manager._on_message(None, None, _Msg("hexe/addons/vision/state/temp", {"ok": True}, retain=False))
                manager._on_message(None, None, _Msg("hexe/scheduler/heartbeat", {"ok": True}, retain=False))
                runtime = await manager.principal_connection_states()
                self.assertIn("addon:vision", runtime)
                self.assertTrue(runtime["addon:vision"]["connected"])
                self.assertIn("core.scheduler", runtime)
                self.assertTrue(runtime["core.scheduler"]["connected"])
            finally:
                if old is None:
                    del os.environ["MQTT_INTEGRATION_STATE_PATH"]
                else:
                    os.environ["MQTT_INTEGRATION_STATE_PATH"] = old

    async def test_topic_activity_limit_prefers_most_recent_topics(self) -> None:
        manager = MqttManager(
            settings_store=_FakeSettingsStore(),
            registry=_FakeRegistry(),
            service_catalog_store=_FakeServiceCatalogStore(),
            enabled=True,
        )
        manager._loop = asyncio.get_running_loop()
        manager._on_message(None, None, _Msg("z/older", {"ok": True}, retain=False))
        await asyncio.sleep(0.01)
        manager._on_message(None, None, _Msg("a/newer", {"ok": True}, retain=False))
        topics = await manager.topic_activity(limit=1)
        self.assertTrue(topics["ok"])
        self.assertEqual(len(topics["items"]), 1)
        self.assertEqual(topics["items"][0]["topic"], "a/newer")

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
                            "core.runtime": {
                                "username": "hx_core.runtime",
                                "password": "core-runtime-secret",
                            },
                            "addon:mqtt": {
                                "username": "hx_mqtt",
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
            self.assertEqual(cfg.username, "hx_core.runtime")
            self.assertEqual(cfg.password, "core-runtime-secret")

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

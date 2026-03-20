import unittest
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.main import create_app
from addons.mqtt.backend.addon import router as mqtt_addon_router


class _FakePrincipal:
    def __init__(self, **values) -> None:
        self._values = values
        for key, value in values.items():
            setattr(self, key, value)

    def model_dump(self, mode: str = "json") -> dict:
        return dict(self._values)


class _FakeIntegrationState:
    def __init__(self, principals) -> None:
        self.principals = principals


class _FakeStateStore:
    async def get_state(self):
        return _FakeIntegrationState(
            {
                "user:homeassistant": _FakePrincipal(
                    principal_id="user:homeassistant",
                    principal_type="generic_user",
                    username="homeassistant",
                    logical_identity="generic:homeassistant",
                    status="active",
                    topic_prefix="external/homeassistant",
                    updated_at="2026-03-18T00:00:00Z",
                ),
                "addon:mqtt": _FakePrincipal(
                    principal_id="addon:mqtt",
                    principal_type="synthia_addon",
                    logical_identity="mqtt",
                    status="active",
                    updated_at="2026-03-18T00:00:00Z",
                ),
            }
        )


class _FakeMqttManager:
    async def principal_connection_states(self):
        return {
            "user:homeassistant": {
                "connected": True,
                "connected_since": "2026-03-18T00:00:00Z",
                "last_seen": "2026-03-18T00:05:00Z",
                "session_count": 1,
            }
        }

    async def principal_traffic_metrics(self):
        return {
            "user:homeassistant": {
                "messages_per_second": 6.0,
                "payload_size": 1024,
                "topic_count": 3,
            }
        }

    async def topic_activity(self, *, limit: int = 500):
        return {
            "ok": True,
            "items": [
                {
                    "topic": "external/homeassistant/living-room/state",
                    "message_count": 8,
                    "last_seen": "2026-03-18T00:03:00Z",
                },
                {
                    "topic": "external/homeassistant/kitchen/state",
                    "message_count": 4,
                    "last_seen": "2026-03-18T00:05:00Z",
                },
                {
                    "topic": "external/homeassistant/living-room/config",
                    "message_count": 2,
                    "last_seen": "2026-03-18T00:04:00Z",
                },
            ],
        }


class TestMqttEmbeddedUiRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_root_ui_page_contains_setup_shell(self) -> None:
        res = self.client.get("/api/addons/mqtt")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("Hexe MQTT Setup", res.text)
        self.assertIn("Save and Initialize", res.text)
        self.assertIn("Local broker", res.text)
        self.assertIn("External broker", res.text)
        self.assertIn("Check Health", res.text)
        self.assertIn("data-runtime-action='start'", res.text)
        self.assertIn('id="host"', res.text)
        self.assertIn('id="port"', res.text)
        self.assertIn('id="username"', res.text)
        self.assertIn('id="password"', res.text)
        self.assertIn("Test Connection", res.text)
        self.assertIn("data-section=\"overview\"", res.text)
        self.assertIn("data-section=\"principals\"", res.text)
        self.assertIn("data-section=\"users\"", res.text)
        self.assertIn("data-section=\"runtime\"", res.text)
        self.assertIn("data-section=\"topics\"", res.text)
        self.assertIn("Live Message Monitor", res.text)
        self.assertIn("Publish Bootstrap", res.text)
        self.assertIn("View Runtime Config", res.text)
        self.assertIn("data-section=\"audit\"", res.text)
        self.assertIn("data-section=\"noisy-clients\"", res.text)
        self.assertIn(".pill {", res.text)
        self.assertIn(".stats {", res.text)
        self.assertIn("Total Principals", res.text)
        self.assertIn("Recent Errors", res.text)
        self.assertIn("data-filter='principals-q'", res.text)
        self.assertIn("data-filter='principals-type'", res.text)
        self.assertIn(">System</option>", res.text)
        self.assertIn(">Generic</option>", res.text)
        self.assertIn("Add User", res.text)
        self.assertIn("data-ui-action='open-add-user'", res.text)
        self.assertIn("id='create-user-username'", res.text)
        self.assertIn("id='create-user-prefix'", res.text)
        self.assertIn("id='create-user-access-mode'", res.text)
        self.assertIn("id='create-user-allowed-topics'", res.text)
        self.assertIn("id='create-user-allowed-publish-topics'", res.text)
        self.assertIn("id='create-user-allowed-subscribe-topics'", res.text)
        self.assertIn("data-generic-action='rotate'", res.text)
        self.assertIn("data-generic-action='edit'", res.text)
        self.assertIn("data-generic-action='delete'", res.text)
        self.assertIn("data-principal-action='activate'", res.text)
        self.assertIn("Topic Prefix", res.text)
        self.assertIn("Core Managed", res.text)
        self.assertIn("System principals are Core-managed", res.text)
        self.assertIn("Core principal registration warning", res.text)
        self.assertIn("Export Users", res.text)
        self.assertIn("Import Users", res.text)
        self.assertIn("data-filter='users-q'", res.text)
        self.assertIn("data-filter='topics-q'", res.text)
        self.assertIn("data-filter='audit-q'", res.text)
        self.assertIn("data-filter='audit-principal'", res.text)
        self.assertIn("data-filter='audit-action'", res.text)
        self.assertIn("data-filter='noisy-q'", res.text)

    def test_subroute_ui_page_serves_same_shell(self) -> None:
        res = self.client.get("/api/addons/mqtt/principals")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("Hexe MQTT Setup", res.text)
        self.assertIn("data-section=\"principals\"", res.text)

    def test_topics_subroute_defaults_to_ui_shell(self) -> None:
        res = self.client.get("/api/addons/mqtt/topics")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("Hexe MQTT Setup", res.text)
        self.assertIn("data-section=\"topics\"", res.text)

    def test_topics_subroute_returns_json_when_requested(self) -> None:
        res = self.client.get("/api/addons/mqtt/topics?format=json")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["items"], list)

    def test_users_subroute_returns_user_and_device_breakdown_json(self) -> None:
        app = FastAPI()
        app.state.mqtt_integration_state_store = _FakeStateStore()
        app.state.mqtt_manager = _FakeMqttManager()
        app.include_router(mqtt_addon_router, prefix="/api/addons/mqtt")
        client = TestClient(app)

        res = client.get("/api/addons/mqtt/users?format=json")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["principal_id"], "user:homeassistant")
        self.assertEqual(item["device_count"], 2)
        self.assertEqual(item["observed_message_count"], 14)
        by_device = {entry["device_id"]: entry for entry in item["devices"]}
        self.assertEqual(by_device["living-room"]["message_count"], 10)
        self.assertEqual(by_device["kitchen"]["message_count"], 4)
        self.assertGreater(by_device["living-room"]["messages_per_second"], by_device["kitchen"]["messages_per_second"])


if __name__ == "__main__":
    unittest.main()

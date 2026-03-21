import json
import tempfile
import unittest
from pathlib import Path

from app.system.mqtt.integration_state import MqttIntegrationStateStore


class TestMqttIntegrationStateNormalization(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_synthia_topics_are_normalized_to_hexe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mqtt_state.json"
            path.write_text(
                json.dumps(
                    {
                        "active_grants": {
                            "mqtt": {
                                "addon_id": "mqtt",
                                "status": "active",
                                "publish_topics": ["synthia/addons/mqtt/event/#"],
                                "subscribe_topics": ["synthia/bootstrap/core", "synthia/addons/mqtt/command/#"],
                            }
                        },
                        "principals": {
                            "addon:mqtt": {
                                "principal_id": "addon:mqtt",
                                "principal_type": "synthia_addon",
                                "status": "active",
                                "logical_identity": "mqtt",
                                "publish_topics": ["synthia/addons/mqtt/state/#"],
                                "subscribe_topics": ["synthia/bootstrap/core"],
                                "allowed_topics": ["synthia/addons/mqtt/#"],
                                "allowed_publish_topics": ["synthia/addons/mqtt/state/#"],
                                "allowed_subscribe_topics": ["synthia/addons/mqtt/command/#"],
                                "approved_reserved_topics": ["synthia/bootstrap/core"],
                                "topic_prefix": "synthia/addons/mqtt/",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            store = MqttIntegrationStateStore(str(path))
            state = await store.get_state()
            self.assertEqual(state.active_grants["mqtt"].publish_topics, ["hexe/addons/mqtt/event/#"])
            self.assertEqual(
                state.active_grants["mqtt"].subscribe_topics,
                ["hexe/bootstrap/core", "hexe/addons/mqtt/command/#"],
            )
            principal = state.principals["addon:mqtt"]
            self.assertEqual(principal.publish_topics, ["hexe/addons/mqtt/state/#"])
            self.assertEqual(principal.subscribe_topics, ["hexe/bootstrap/core"])
            self.assertEqual(principal.allowed_topics, ["hexe/addons/mqtt/#"])
            self.assertEqual(principal.approved_reserved_topics, ["hexe/bootstrap/core"])
            self.assertEqual(principal.topic_prefix, "hexe/addons/mqtt/")
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("hexe/bootstrap/core", json.dumps(persisted))
            self.assertNotIn("synthia/bootstrap/core", json.dumps(persisted))

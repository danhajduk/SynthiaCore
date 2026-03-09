import asyncio
import tempfile
import unittest
from pathlib import Path

from app.system.mqtt.observability_store import MqttObservabilityStore


class TestMqttObservabilityStore(unittest.TestCase):
    def test_append_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MqttObservabilityStore(str(Path(tmp) / "mqtt_obsv.db"))
            row = asyncio.run(
                store.append_event(
                    event_type="denied_topic_attempt",
                    source="mqtt_approval",
                    severity="warn",
                    metadata={"addon_id": "vision"},
                )
            )
            self.assertGreater(row["id"], 0)
            rows = asyncio.run(store.list_events(limit=10))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["event_type"], "denied_topic_attempt")


if __name__ == "__main__":
    unittest.main()

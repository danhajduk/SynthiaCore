import asyncio
import tempfile
import unittest
from pathlib import Path

from app.system.mqtt.authority_audit import MqttAuthorityAuditStore


class TestMqttAuthorityAuditStore(unittest.TestCase):
    def test_append_and_list_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MqttAuthorityAuditStore(str(Path(tmp) / "mqtt_audit.db"))
            created = asyncio.run(
                store.append_event(
                    event_type="mqtt_apply",
                    status="applied",
                    payload={"files": ["acl.conf"]},
                )
            )
            self.assertGreater(created["id"], 0)
            items = asyncio.run(store.list_events(limit=10))
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["event_type"], "mqtt_apply")


if __name__ == "__main__":
    unittest.main()

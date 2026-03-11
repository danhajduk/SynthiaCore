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
                    payload={"files": ["acl.conf"], "principal_id": "user:guest1", "action": "apply_config"},
                )
            )
            self.assertGreater(created["id"], 0)
            items = asyncio.run(store.list_events(limit=10))
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["event_type"], "mqtt_apply")
            self.assertEqual(items[0]["actor_principal"], "user:guest1")
            self.assertEqual(items[0]["action"], "apply_config")
            self.assertEqual(items[0]["result"], "applied")
            self.assertTrue(items[0]["timestamp"])
            filtered = asyncio.run(store.list_events(limit=10, principal="guest1", action="apply"))
            self.assertEqual(len(filtered), 1)


if __name__ == "__main__":
    unittest.main()

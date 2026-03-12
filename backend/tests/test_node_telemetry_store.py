import tempfile
import unittest
from pathlib import Path

from app.system.onboarding.node_telemetry import NodeTelemetryService, NodeTelemetryStore


class TestNodeTelemetryStore(unittest.TestCase):
    def test_ingest_and_latest_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = NodeTelemetryStore(path=Path(tmpdir) / "node_telemetry_events.json", max_items=5)
            service = NodeTelemetryService(store)
            first = service.ingest(
                node_id="node-a",
                event_type="lifecycle_transition",
                event_state="running",
                message="runtime up",
                payload={"stage": "boot", "details": {"ok": True}},
            )
            self.assertEqual(first.node_id, "node-a")
            self.assertEqual(first.event_type, "lifecycle_transition")
            self.assertEqual(first.payload.get("stage"), "boot")
            self.assertEqual(first.payload.get("details", {}).get("ok"), True)

            second = service.ingest(
                node_id="node-a",
                event_type="governance_sync",
                event_state="synced",
                message="governance synced",
                payload={"version": "gov-v1"},
            )
            self.assertEqual(service.latest_timestamp("node-a"), second.received_at)
            events = service.list_events(node_id="node-a", limit=10)
            self.assertEqual(len(events), 2)

    def test_rejects_unsupported_event_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = NodeTelemetryStore(path=Path(tmpdir) / "node_telemetry_events.json")
            service = NodeTelemetryService(store)
            with self.assertRaises(ValueError):
                service.ingest(node_id="node-a", event_type="unknown_event")


if __name__ == "__main__":
    unittest.main()

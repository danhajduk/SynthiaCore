from __future__ import annotations

import unittest
from typing import Any

from app.core import CoreStartupNotificationProducer


class _FakeNotificationPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def publish_internal_popup(self, payload: dict[str, Any], *, qos: int = 1) -> dict[str, Any]:
        self.calls.append(("popup", payload, {"qos": qos}))
        return {"ok": True, "topic": "synthia/notify/internal/popup", "message_id": "popup-1"}

    async def publish_internal_event(self, payload: dict[str, Any], *, qos: int = 1) -> dict[str, Any]:
        self.calls.append(("event", payload, {"qos": qos}))
        return {"ok": True, "topic": "synthia/notify/internal/event", "message_id": "event-1"}

    async def publish_internal_state(self, payload: dict[str, Any], *, qos: int = 1, retain: bool = False) -> dict[str, Any]:
        self.calls.append(("state", payload, {"qos": qos, "retain": retain}))
        return {"ok": True, "topic": "synthia/notify/internal/state", "message_id": "state-1"}


class TestNotificationProducer(unittest.IsolatedAsyncioTestCase):
    async def test_startup_producer_emits_popup_event_and_state(self) -> None:
        publisher = _FakeNotificationPublisher()
        producer = CoreStartupNotificationProducer(publisher, core_version="0.1.0")

        results = await producer.emit_startup_notifications()

        self.assertEqual([item[0] for item in publisher.calls], ["popup", "event", "state"])
        self.assertEqual([item["topic"] for item in results], [
            "synthia/notify/internal/popup",
            "synthia/notify/internal/event",
            "synthia/notify/internal/state",
        ])
        popup_payload = publisher.calls[0][1]
        event_payload = publisher.calls[1][1]
        state_payload = publisher.calls[2][1]
        self.assertEqual(popup_payload["source"]["component"], "startup")
        self.assertEqual(event_payload["event"]["event_type"], "core_startup_complete")
        self.assertEqual(state_payload["state"]["status"], "ready")
        self.assertTrue(bool(state_payload["targets"]["hosts"]))
        self.assertTrue(publisher.calls[2][2]["retain"])

    async def test_startup_producer_logs_each_emission(self) -> None:
        publisher = _FakeNotificationPublisher()
        producer = CoreStartupNotificationProducer(publisher, core_version="0.1.0")

        with self.assertLogs("synthia.core.notifications", level="INFO") as logs:
            await producer.emit_startup_notifications()

        joined = "\n".join(logs.output)
        self.assertIn("startup_notification_emitted type=popup", joined)
        self.assertIn("startup_notification_emitted type=event", joined)
        self.assertIn("startup_notification_emitted type=state", joined)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from typing import Any

from app.core import CoreNotificationPublisher, INTERNAL_EVENT_TOPIC, INTERNAL_POPUP_TOPIC, INTERNAL_STATE_TOPIC


class _FakeMqttPublisher:
    def __init__(self, *, raise_error: bool = False, ok: bool = True) -> None:
        self.raise_error = raise_error
        self.ok = ok
        self.calls: list[dict[str, Any]] = []

    async def publish(self, topic: str, payload: dict[str, Any], retain: bool = True, qos: int = 1) -> dict[str, Any]:
        if self.raise_error:
            raise RuntimeError("boom")
        self.calls.append({"topic": topic, "payload": payload, "retain": retain, "qos": qos})
        return {"ok": self.ok, "topic": topic, "rc": 0 if self.ok else 5}


class TestNotificationPublisher(unittest.IsolatedAsyncioTestCase):
    def _payload(self) -> dict[str, Any]:
        return {
            "source": {"kind": "core", "id": "core", "component": "startup"},
            "targets": {"broadcast": True},
            "delivery": {"severity": "info", "priority": "normal"},
            "content": {"title": "Synthia", "message": "Ready"},
            "event": {"event_type": "startup_complete"},
        }

    async def test_event_publish_uses_internal_topic_and_non_retained_payload(self) -> None:
        mqtt = _FakeMqttPublisher()
        publisher = CoreNotificationPublisher(mqtt)

        result = await publisher.publish_internal_event(self._payload(), qos=2)

        self.assertTrue(result["ok"])
        self.assertEqual(mqtt.calls[0]["topic"], INTERNAL_EVENT_TOPIC)
        self.assertFalse(mqtt.calls[0]["retain"])
        self.assertEqual(mqtt.calls[0]["qos"], 2)
        self.assertIn("event", mqtt.calls[0]["payload"]["delivery"]["channels"])
        self.assertNotIn("state", mqtt.calls[0]["payload"])

    async def test_popup_publish_forces_non_retained_messages(self) -> None:
        mqtt = _FakeMqttPublisher()
        publisher = CoreNotificationPublisher(mqtt)

        result = await publisher.publish_internal_popup(self._payload())

        self.assertTrue(result["ok"])
        self.assertEqual(mqtt.calls[0]["topic"], INTERNAL_POPUP_TOPIC)
        self.assertFalse(mqtt.calls[0]["retain"])
        self.assertIn("popup", mqtt.calls[0]["payload"]["delivery"]["channels"])

    async def test_state_publish_allows_explicit_retention(self) -> None:
        mqtt = _FakeMqttPublisher()
        publisher = CoreNotificationPublisher(mqtt)
        payload = self._payload()
        payload.pop("event", None)
        payload["state"] = {"state_type": "service_health", "status": "ready"}

        result = await publisher.publish_internal_state(payload, retain=True)

        self.assertTrue(result["ok"])
        self.assertEqual(mqtt.calls[0]["topic"], INTERNAL_STATE_TOPIC)
        self.assertTrue(mqtt.calls[0]["retain"])
        self.assertIn("state", mqtt.calls[0]["payload"]["delivery"]["channels"])

    async def test_publish_excludes_none_sections(self) -> None:
        mqtt = _FakeMqttPublisher()
        publisher = CoreNotificationPublisher(mqtt)
        payload = self._payload()
        payload["content"]["body"] = None

        await publisher.publish_internal_popup(payload)

        self.assertNotIn("body", mqtt.calls[0]["payload"]["content"])

    async def test_invalid_payload_is_blocked_before_publish(self) -> None:
        mqtt = _FakeMqttPublisher()
        publisher = CoreNotificationPublisher(mqtt)

        result = await publisher.publish_internal_event({"source": {"kind": "core", "id": "core"}})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "notification_invalid")
        self.assertEqual(mqtt.calls, [])

    async def test_publish_failure_is_reported(self) -> None:
        mqtt = _FakeMqttPublisher(raise_error=True)
        publisher = CoreNotificationPublisher(mqtt)

        result = await publisher.publish_internal_event(self._payload())

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "mqtt_publish_failed")

    async def test_mqtt_negative_result_is_logged_as_failure_response(self) -> None:
        mqtt = _FakeMqttPublisher(ok=False)
        publisher = CoreNotificationPublisher(mqtt)

        result = await publisher.publish_internal_event(self._payload())

        self.assertFalse(result["ok"])
        self.assertEqual(mqtt.calls[0]["topic"], INTERNAL_EVENT_TOPIC)


if __name__ == "__main__":
    unittest.main()

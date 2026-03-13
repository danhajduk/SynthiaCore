from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core import NotificationBridgeService


class _FakeManager:
    def __init__(self) -> None:
        self.listeners: dict[str, tuple[str, Any]] = {}
        self.counter = 0

    def register_message_listener(self, *, topic_filter: str, callback):
        self.counter += 1
        listener_id = f"listener-{self.counter}"
        self.listeners[listener_id] = (topic_filter, callback)
        return listener_id

    def unregister_message_listener(self, listener_id: str) -> bool:
        return self.listeners.pop(listener_id, None) is not None


class _FakePublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def publish(self, topic: str, payload: dict[str, Any], retain: bool = True, qos: int = 1) -> dict[str, Any]:
        self.calls.append({"topic": topic, "payload": payload, "retain": retain, "qos": qos})
        return {"ok": True, "topic": topic, "rc": 0}


class TestNotificationBridge(unittest.IsolatedAsyncioTestCase):
    def _payload(self, **overrides) -> dict[str, Any]:
        payload = {
            "source": {"kind": "core", "id": "synthia-core", "component": "startup"},
            "targets": {"broadcast": True, "external": ["ha"]},
            "delivery": {"severity": "warning", "priority": "high", "dedupe_key": "alert-tag", "channels": ["event"]},
            "content": {"title": "Alert", "message": "Attention"},
            "event": {"event_type": "core_alert", "summary": "Important alert"},
        }
        payload.update(overrides)
        return payload

    async def test_bridge_forwards_supported_external_targets(self) -> None:
        publisher = _FakePublisher()
        manager = _FakeManager()
        bridge = NotificationBridgeService(publisher, manager)

        await bridge._handle_runtime_message("synthia/notify/internal/event", self._payload(), False)

        self.assertEqual(len(publisher.calls), 1)
        self.assertEqual(publisher.calls[0]["topic"], "synthia/notify/external/ha")
        self.assertEqual(publisher.calls[0]["payload"]["title"], "Alert")
        self.assertEqual(publisher.calls[0]["payload"]["message"], "Attention\nImportant alert")
        self.assertEqual(publisher.calls[0]["payload"]["severity"], "warning")
        self.assertEqual(publisher.calls[0]["payload"]["tag"], "alert-tag")
        self.assertEqual(publisher.calls[0]["payload"]["kind"], "event")
        self.assertFalse(publisher.calls[0]["retain"])

    async def test_bridge_skips_messages_without_external_targets(self) -> None:
        publisher = _FakePublisher()
        bridge = NotificationBridgeService(publisher, _FakeManager())

        payload = self._payload(targets={"broadcast": True})
        await bridge._handle_runtime_message("synthia/notify/internal/event", payload, False)

        self.assertEqual(publisher.calls, [])

    async def test_bridge_skips_expired_messages(self) -> None:
        publisher = _FakePublisher()
        bridge = NotificationBridgeService(publisher, _FakeManager())
        payload = self._payload(
            created_at=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
            delivery={"severity": "warning", "priority": "high", "dedupe_key": "alert-tag", "channels": ["event"], "ttl_seconds": 5},
        )

        await bridge._handle_runtime_message("synthia/notify/internal/event", payload, False)

        self.assertEqual(publisher.calls, [])

    async def test_bridge_skips_invalid_messages(self) -> None:
        publisher = _FakePublisher()
        bridge = NotificationBridgeService(publisher, _FakeManager())

        await bridge._handle_runtime_message("synthia/notify/internal/event", {"bad": "payload"}, False)

        self.assertEqual(publisher.calls, [])

    async def test_bridge_ignores_unsupported_targets(self) -> None:
        publisher = _FakePublisher()
        bridge = NotificationBridgeService(publisher, _FakeManager())
        payload = self._payload(targets={"broadcast": True, "external": ["other"]})

        await bridge._handle_runtime_message("synthia/notify/internal/event", payload, False)

        self.assertEqual(publisher.calls, [])

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from app.core import LocalDesktopNotificationConsumer


class _FakeMqttManager:
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


class TestNotificationConsumer(unittest.IsolatedAsyncioTestCase):
    def _payload(self, **overrides) -> dict[str, Any]:
        payload = {
            "source": {"kind": "core", "id": "synthia-core", "component": "startup", "host": "test-host", "user": "dan"},
            "targets": {"hosts": ["test-host"]},
            "delivery": {"severity": "info", "priority": "normal", "channels": ["popup"], "dedupe_key": "startup"},
            "content": {"title": "Ready", "message": "Started"},
            "event": {"event_type": "core_startup_complete", "summary": "ready"},
        }
        payload.update(overrides)
        return payload

    async def test_consumer_registers_popup_and_event_filters(self) -> None:
        mqtt = _FakeMqttManager()
        consumer = LocalDesktopNotificationConsumer(mqtt, notifier_cmd="/usr/bin/notify-send")

        await consumer.start()

        filters = [item[0] for item in mqtt.listeners.values()]
        self.assertEqual(filters, ["synthia/notify/internal/popup", "synthia/notify/internal/event"])

    async def test_matching_popup_notification_is_displayed(self) -> None:
        mqtt = _FakeMqttManager()
        consumer = LocalDesktopNotificationConsumer(mqtt, notifier_cmd="/usr/bin/notify-send")
        consumer._hostname = "test-host"
        consumer._user = "dan"
        await consumer.start()

        with patch("app.core.notification_consumer.subprocess.run") as run_mock:
            await consumer._handle_runtime_message("synthia/notify/internal/popup", self._payload(), False)

        run_mock.assert_called_once()

    async def test_invalid_notification_is_ignored(self) -> None:
        mqtt = _FakeMqttManager()
        consumer = LocalDesktopNotificationConsumer(mqtt, notifier_cmd="/usr/bin/notify-send")

        with patch("app.core.notification_consumer.subprocess.run") as run_mock:
            await consumer._handle_runtime_message("synthia/notify/internal/popup", {"source": {"kind": "core"}}, False)

        run_mock.assert_not_called()

    async def test_target_mismatch_is_ignored(self) -> None:
        mqtt = _FakeMqttManager()
        consumer = LocalDesktopNotificationConsumer(mqtt, notifier_cmd="/usr/bin/notify-send")
        consumer._hostname = "host-a"
        consumer._user = "alex"

        with patch("app.core.notification_consumer.subprocess.run") as run_mock:
            await consumer._handle_runtime_message("synthia/notify/internal/popup", self._payload(), False)

        run_mock.assert_not_called()

    async def test_duplicate_dedupe_key_is_ignored(self) -> None:
        mqtt = _FakeMqttManager()
        consumer = LocalDesktopNotificationConsumer(mqtt, notifier_cmd="/usr/bin/notify-send")
        consumer._hostname = "test-host"
        consumer._user = "dan"
        payload = self._payload()

        with patch("app.core.notification_consumer.subprocess.run") as run_mock:
            await consumer._handle_runtime_message("synthia/notify/internal/popup", payload, False)
            await consumer._handle_runtime_message("synthia/notify/internal/popup", payload, False)

        self.assertEqual(run_mock.call_count, 1)

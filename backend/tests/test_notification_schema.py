from __future__ import annotations

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from app.core import (
    INTERNAL_EVENT_TOPIC,
    INTERNAL_POPUP_TOPIC,
    INTERNAL_STATE_TOPIC,
    NotificationChannel,
    NotificationContent,
    NotificationEvent,
    NotificationMessage,
    NotificationPriority,
    NotificationSeverity,
    NotificationSource,
    NotificationSourceKind,
    NotificationState,
    NotificationTargets,
    external_notification_topic,
    notification_message_from_json,
    notification_message_to_json,
)


class TestNotificationSchema(unittest.TestCase):
    def _message(self, **overrides) -> NotificationMessage:
        payload = {
            "source": NotificationSource(kind=NotificationSourceKind.CORE, id="core", component="startup"),
            "targets": NotificationTargets(users=["dan"]),
            "delivery": {
                "severity": NotificationSeverity.INFO,
                "priority": NotificationPriority.NORMAL,
                "channels": [NotificationChannel.POPUP, NotificationChannel.EVENT],
                "ttl_seconds": 60,
                "dedupe_key": "startup-complete",
            },
            "content": NotificationContent(title="Synthia", message="Startup complete"),
            "event": NotificationEvent(event_type="startup_complete"),
            "data": {"phase": "ready"},
        }
        payload.update(overrides)
        return NotificationMessage.model_validate(payload)

    def test_valid_message_round_trips_json(self) -> None:
        message = self._message()

        raw = notification_message_to_json(message)
        parsed = notification_message_from_json(raw)

        self.assertEqual(parsed.source.kind, NotificationSourceKind.CORE)
        self.assertEqual(parsed.delivery.channels, [NotificationChannel.POPUP, NotificationChannel.EVENT])
        self.assertEqual(parsed.content.message, "Startup complete")
        self.assertNotIn('"state": null', raw)

    def test_valid_popup_message_is_accepted(self) -> None:
        message = self._message(event=None, delivery={"channels": ["popup"]}, data=None)
        self.assertEqual(message.delivery.channels, [NotificationChannel.POPUP])

    def test_valid_event_message_is_accepted(self) -> None:
        message = self._message(content=None, delivery={"channels": ["event"]}, data=None)
        self.assertEqual(message.event.event_type, "startup_complete")

    def test_broadcast_target_behavior_is_valid(self) -> None:
        message = self._message(targets={"broadcast": True}, delivery={"channels": ["event"]}, content=None, data=None)
        self.assertTrue(message.targets.broadcast)

    def test_targets_require_scope_or_broadcast(self) -> None:
        with self.assertRaises(ValidationError):
            NotificationTargets()

    def test_message_requires_payload_section(self) -> None:
        with self.assertRaises(ValidationError):
            NotificationMessage.model_validate(
                {
                    "source": {"kind": "core", "id": "core"},
                    "targets": {"broadcast": True},
                    "delivery": {"channels": ["event"]},
                }
            )

    def test_event_payload_cannot_be_empty(self) -> None:
        with self.assertRaises(ValidationError):
            self._message(event={})

    def test_state_payload_cannot_be_empty(self) -> None:
        with self.assertRaises(ValidationError):
            self._message(state={})

    def test_message_expires_when_ttl_passes(self) -> None:
        created_at = datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc).isoformat()
        message = self._message(created_at=created_at)

        self.assertFalse(message.is_expired(at=datetime(2026, 3, 12, 12, 0, 59, tzinfo=timezone.utc)))
        self.assertTrue(message.is_expired(at=datetime(2026, 3, 12, 12, 1, 0, tzinfo=timezone.utc)))

    def test_state_only_message_is_valid(self) -> None:
        message = self._message(
            content=None,
            event=None,
            state=NotificationState(state_type="service_health", status="degraded"),
            data=None,
            delivery={"channels": ["state"], "severity": "warning"},
        )

        self.assertEqual(message.state.status, "degraded")
        self.assertEqual(message.delivery.channels, [NotificationChannel.STATE])

    def test_topic_helpers_expose_canonical_paths(self) -> None:
        self.assertEqual(INTERNAL_EVENT_TOPIC, "synthia/notify/internal/event")
        self.assertEqual(INTERNAL_STATE_TOPIC, "synthia/notify/internal/state")
        self.assertEqual(INTERNAL_POPUP_TOPIC, "synthia/notify/internal/popup")
        self.assertEqual(external_notification_topic("ha"), "synthia/notify/external/ha")
        with self.assertRaises(ValueError):
            external_notification_topic("bad target")


if __name__ == "__main__":
    unittest.main()

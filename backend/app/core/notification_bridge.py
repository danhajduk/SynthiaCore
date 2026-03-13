from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from .notification_publisher import NotificationMqttPublisher
from .notifications import NotificationMessage, external_notification_topic


class NotificationBridgeService:
    def __init__(self, mqtt_publisher: NotificationMqttPublisher, mqtt_manager) -> None:
        self._publisher = mqtt_publisher
        self._mqtt_manager = mqtt_manager
        self._log = logging.getLogger("synthia.core.notifications")
        self._listener_ids: list[str] = []

    async def start(self) -> None:
        if self._listener_ids:
            return
        self._listener_ids.append(
            self._mqtt_manager.register_message_listener(
                topic_filter="synthia/notify/internal/#",
                callback=self._handle_runtime_message,
            )
        )
        self._log.info("notification_bridge_started topic_filter=synthia/notify/internal/#")

    async def stop(self) -> None:
        for listener_id in list(self._listener_ids):
            self._mqtt_manager.unregister_message_listener(listener_id)
        self._listener_ids.clear()

    async def _handle_runtime_message(self, topic: str, payload: dict[str, Any], retained: bool) -> None:
        try:
            message = NotificationMessage.model_validate(payload)
        except ValidationError as exc:
            self._log.warning("notification_bridge_dropped topic=%s reason=invalid error=%s", topic, exc.errors())
            return
        if message.is_expired():
            self._log.info("notification_bridge_dropped topic=%s reason=expired message_id=%s", topic, message.id)
            return

        external_targets = [target for target in message.targets.external if str(target).strip()]
        if not external_targets:
            self._log.info("notification_bridge_skipped topic=%s reason=no_external_targets message_id=%s", topic, message.id)
            return

        forwarded = False
        for target in external_targets:
            if str(target).strip().lower() != "ha":
                self._log.info(
                    "notification_bridge_skipped topic=%s reason=unsupported_target target=%s message_id=%s",
                    topic,
                    target,
                    message.id,
                )
                continue
            bridge_topic = external_notification_topic(target)
            bridge_payload = self._to_external_payload(message=message, source_topic=topic)
            result = await self._publisher.publish(topic=bridge_topic, payload=bridge_payload, retain=False, qos=1)
            if bool(result.get("ok")):
                forwarded = True
                self._log.info(
                    "notification_bridge_forwarded source_topic=%s target_topic=%s target=%s message_id=%s",
                    topic,
                    bridge_topic,
                    target,
                    message.id,
                )
            else:
                self._log.warning(
                    "notification_bridge_dropped source_topic=%s reason=publish_failed target=%s result=%s message_id=%s",
                    topic,
                    target,
                    result,
                    message.id,
                )
        if not forwarded:
            self._log.info("notification_bridge_skipped topic=%s reason=no_forwarded_targets message_id=%s", topic, message.id)

    def _to_external_payload(self, *, message: NotificationMessage, source_topic: str) -> dict[str, Any]:
        title = (
            (message.content.title if message.content is not None else None)
            or (message.event.summary if message.event is not None else None)
            or (message.event.event_type if message.event is not None else None)
            or (message.state.status if message.state is not None else None)
            or "Synthia Notification"
        )
        body_parts = [
            message.content.message if message.content is not None else None,
            message.content.body if message.content is not None else None,
            message.event.summary if message.event is not None else None,
            message.state.status if message.state is not None else None,
        ]
        payload = {
            "title": title,
            "message": "\n".join([str(item).strip() for item in body_parts if str(item or "").strip()]) or title,
            "severity": message.delivery.severity.value,
            "tag": message.delivery.dedupe_key,
            "kind": self._notification_kind(source_topic),
            "created_at": message.created_at,
            "source": {
                "kind": message.source.kind.value,
                "id": message.source.id,
                "component": message.source.component,
            },
        }
        return {key: value for key, value in payload.items() if value is not None}

    @staticmethod
    def _notification_kind(source_topic: str) -> str:
        topic = str(source_topic or "").strip()
        if topic.endswith("/popup"):
            return "popup"
        if topic.endswith("/state"):
            return "state"
        return "event"

from __future__ import annotations

import logging
from typing import Any, Protocol

from pydantic import ValidationError

from .notifications import (
    INTERNAL_EVENT_TOPIC,
    INTERNAL_POPUP_TOPIC,
    INTERNAL_STATE_TOPIC,
    NotificationChannel,
    NotificationDelivery,
    NotificationMessage,
)


class NotificationMqttPublisher(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any], retain: bool = True, qos: int = 1) -> dict[str, Any]:
        ...


class CoreNotificationPublisher:
    def __init__(self, mqtt_publisher: NotificationMqttPublisher) -> None:
        self._mqtt = mqtt_publisher
        self._log = logging.getLogger("synthia.core.notifications")

    async def publish_message(
        self,
        message: NotificationMessage | dict[str, Any],
        *,
        topic: str,
        qos: int = 1,
        retain: bool = False,
    ) -> dict[str, Any]:
        try:
            parsed = message if isinstance(message, NotificationMessage) else NotificationMessage.model_validate(message)
        except ValidationError as exc:
            self._log.warning("notification_publish_invalid topic=%s error=%s", topic, exc.errors())
            return {"ok": False, "error": "notification_invalid", "topic": topic}

        payload = parsed.to_payload(exclude_none=True)
        try:
            result = await self._mqtt.publish(topic=topic, payload=payload, retain=retain, qos=qos)
        except Exception as exc:
            self._log.exception(
                "notification_publish_failed topic=%s message_id=%s error=%s",
                topic,
                parsed.id,
                type(exc).__name__,
            )
            return {
                "ok": False,
                "error": "mqtt_publish_failed",
                "topic": topic,
                "message_id": parsed.id,
            }

        output = {"message_id": parsed.id, **dict(result or {}), "topic": topic}
        if bool(output.get("ok")):
            self._log.info(
                "notification_published topic=%s message_id=%s qos=%s retain=%s",
                topic,
                parsed.id,
                int(qos),
                bool(retain),
            )
        else:
            self._log.warning(
                "notification_publish_rejected topic=%s message_id=%s qos=%s retain=%s result=%s",
                topic,
                parsed.id,
                int(qos),
                bool(retain),
                output,
            )
        return output

    async def publish_internal_event(
        self,
        message: NotificationMessage | dict[str, Any],
        *,
        qos: int = 1,
    ) -> dict[str, Any]:
        try:
            prepared = self._prepare_message(message, channel=NotificationChannel.EVENT)
        except ValidationError as exc:
            return self._invalid_result(INTERNAL_EVENT_TOPIC, exc)
        return await self.publish_message(prepared, topic=INTERNAL_EVENT_TOPIC, qos=qos, retain=False)

    async def publish_internal_popup(
        self,
        message: NotificationMessage | dict[str, Any],
        *,
        qos: int = 1,
    ) -> dict[str, Any]:
        try:
            prepared = self._prepare_message(message, channel=NotificationChannel.POPUP)
        except ValidationError as exc:
            return self._invalid_result(INTERNAL_POPUP_TOPIC, exc)
        return await self.publish_message(prepared, topic=INTERNAL_POPUP_TOPIC, qos=qos, retain=False)

    async def publish_internal_state(
        self,
        message: NotificationMessage | dict[str, Any],
        *,
        qos: int = 1,
        retain: bool = False,
    ) -> dict[str, Any]:
        try:
            prepared = self._prepare_message(message, channel=NotificationChannel.STATE)
        except ValidationError as exc:
            return self._invalid_result(INTERNAL_STATE_TOPIC, exc)
        return await self.publish_message(prepared, topic=INTERNAL_STATE_TOPIC, qos=qos, retain=retain)

    def _prepare_message(
        self,
        message: NotificationMessage | dict[str, Any],
        *,
        channel: NotificationChannel,
    ) -> NotificationMessage:
        parsed = message if isinstance(message, NotificationMessage) else NotificationMessage.model_validate(message)
        channels = list(parsed.delivery.channels)
        if channel not in channels:
            channels.append(channel)
        delivery = NotificationDelivery(
            severity=parsed.delivery.severity,
            priority=parsed.delivery.priority,
            urgency=parsed.delivery.urgency,
            channels=channels,
            ttl_seconds=parsed.delivery.ttl_seconds,
            dedupe_key=parsed.delivery.dedupe_key,
        )
        return parsed.model_copy(update={"delivery": delivery})

    def _invalid_result(self, topic: str, exc: ValidationError) -> dict[str, Any]:
        self._log.warning("notification_publish_invalid topic=%s error=%s", topic, exc.errors())
        return {"ok": False, "error": "notification_invalid", "topic": topic}

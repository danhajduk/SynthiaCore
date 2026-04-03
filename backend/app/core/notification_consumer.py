from __future__ import annotations

import asyncio
import logging
import os
import shutil
import socket
import subprocess
import time
from typing import Any

from pydantic import ValidationError

from .notifications import NotificationChannel, NotificationMessage
from app.system.platform_identity import default_platform_naming


class LocalDesktopNotificationConsumer:
    def __init__(self, mqtt_manager, *, notifier_cmd: str | None = None) -> None:
        self._mqtt = mqtt_manager
        self._log = logging.getLogger("synthia.core.notifications")
        self._hostname = socket.gethostname().strip() or "localhost"
        self._user = (os.getenv("USER") or os.getenv("USERNAME") or "").strip() or None
        self._session = (
            os.getenv("XDG_SESSION_ID")
            or os.getenv("DESKTOP_SESSION")
            or os.getenv("WAYLAND_DISPLAY")
            or os.getenv("DISPLAY")
            or ""
        ).strip() or None
        self._notifier_cmd = notifier_cmd or shutil.which("notify-send") or "notify-send"
        self._listener_ids: list[str] = []
        self._dedupe_seen_at: dict[str, float] = {}

    async def start(self) -> None:
        if self._listener_ids:
            return
        self._listener_ids.append(
            self._mqtt.register_message_listener(
                topic_filter="hexe/notify/internal/popup",
                callback=self._handle_runtime_message,
            )
        )
        self._listener_ids.append(
            self._mqtt.register_message_listener(
                topic_filter="hexe/notify/internal/event",
                callback=self._handle_runtime_message,
            )
        )
        self._log.info(
            "desktop_notification_consumer_started user=%s host=%s session=%s notifier=%s",
            self._user,
            self._hostname,
            self._session,
            self._notifier_cmd,
        )

    async def stop(self) -> None:
        for listener_id in list(self._listener_ids):
            self._mqtt.unregister_message_listener(listener_id)
        self._listener_ids.clear()

    async def _handle_runtime_message(self, topic: str, payload: dict[str, Any], retained: bool) -> None:
        try:
            message = NotificationMessage.model_validate(payload)
        except ValidationError as exc:
            self._log.warning("desktop_notification_invalid topic=%s error=%s", topic, exc.errors())
            return

        if message.is_expired():
            self._log.info("desktop_notification_expired topic=%s message_id=%s", topic, message.id)
            return
        if NotificationChannel.POPUP not in message.delivery.channels:
            self._log.info("desktop_notification_ignored topic=%s reason=no_popup_channel message_id=%s", topic, message.id)
            return
        if not self._matches_targets(message):
            self._log.info("desktop_notification_ignored topic=%s reason=target_mismatch message_id=%s", topic, message.id)
            return
        if self._is_duplicate(message):
            self._log.info("desktop_notification_ignored topic=%s reason=dedupe message_id=%s", topic, message.id)
            return

        shown = await self._show_notification(message)
        if shown:
            self._log.info("desktop_notification_accepted topic=%s message_id=%s retained=%s", topic, message.id, retained)
        else:
            self._log.warning("desktop_notification_ignored topic=%s reason=display_failed message_id=%s", topic, message.id)

    def _matches_targets(self, message: NotificationMessage) -> bool:
        targets = message.targets
        if targets.broadcast:
            return True
        if self._user and self._user in targets.users:
            return True
        if self._hostname in targets.hosts:
            return True
        if self._session and self._session in targets.sessions:
            return True
        return False

    def _is_duplicate(self, message: NotificationMessage) -> bool:
        key = str(message.delivery.dedupe_key or "").strip()
        if not key:
            return False
        now = time.time()
        ttl = float(message.delivery.ttl_seconds or 300)
        prior = self._dedupe_seen_at.get(key)
        self._dedupe_seen_at[key] = now
        cutoff = now - max(ttl, 60.0)
        self._dedupe_seen_at = {item_key: ts for item_key, ts in self._dedupe_seen_at.items() if ts >= cutoff}
        return prior is not None and (now - prior) <= max(ttl, 60.0)

    async def _show_notification(self, message: NotificationMessage) -> bool:
        naming = default_platform_naming()
        title = (
            (message.content.title if message.content is not None else None)
            or (message.event.summary if message.event is not None else None)
            or (message.state.status if message.state is not None else None)
            or f"{naming.platform()} Notification"
        )
        body_parts = [
            message.content.message if message.content is not None else None,
            message.content.body if message.content is not None else None,
            message.event.summary if message.event is not None else None,
        ]
        body = "\n".join([str(item).strip() for item in body_parts if str(item or "").strip()]) or "Notification received"
        urgency = {
            "urgent": "critical",
            "error": "critical",
            "actions_needed": "normal",
            "notification": "normal",
            "info": "low",
        }.get(
            (message.delivery.urgency.value if message.delivery.urgency is not None else ""),
            {
                "critical": "critical",
                "error": "critical",
                "warning": "normal",
                "success": "low",
                "info": "low",
            }.get(message.delivery.severity.value, "normal"),
        )
        expire_ms = int(message.delivery.ttl_seconds * 1000) if message.delivery.ttl_seconds is not None else 5000

        try:
            await asyncio.to_thread(
                subprocess.run,
                [self._notifier_cmd, "--urgency", urgency, "--expire-time", str(expire_ms), title, body],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            self._log.exception("desktop_notification_display_failed message_id=%s", message.id)
            return False
        return True

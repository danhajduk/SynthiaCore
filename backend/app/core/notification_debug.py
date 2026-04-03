from __future__ import annotations

import getpass
import logging
import socket
from typing import Any

from app.system.platform_identity import default_platform_naming
from .notification_publisher import CoreNotificationPublisher


class DevelopmentNotificationTrigger:
    def __init__(self, publisher: CoreNotificationPublisher, *, core_version: str = "0.1.0") -> None:
        self._publisher = publisher
        self._core_version = str(core_version or "0.1.0").strip() or "0.1.0"
        self._log = logging.getLogger("synthia.core.notifications")

    async def emit_test_flow(self) -> list[dict[str, Any]]:
        naming = default_platform_naming()
        hostname = socket.gethostname().strip() or "localhost"
        username = self._current_user()

        popup_result = await self._publisher.publish_internal_popup(
            {
                "source": {"kind": "core", "id": "hexe-core", "component": "debug", "host": hostname, "user": username},
                "targets": {"hosts": [hostname], "users": [username] if username else []},
                "delivery": {"severity": "info", "priority": "normal", "ttl_seconds": 300, "dedupe_key": "dev-popup"},
                "content": {"title": f"{naming.platform_short()} Debug Popup", "message": "Developer-triggered popup notification."},
                "event": {"event_type": "debug_popup", "summary": "Debug popup flow"},
                "data": {"debug": True, "core_version": self._core_version},
            }
        )
        self._log_result("popup", popup_result)

        event_result = await self._publisher.publish_internal_event(
            {
                "source": {"kind": "core", "id": "hexe-core", "component": "debug", "host": hostname, "user": username},
                "targets": {"broadcast": True, "external": ["ha"]},
                "delivery": {"severity": "warning", "priority": "high", "dedupe_key": "dev-event-ha"},
                "content": {"title": f"{naming.platform_short()} Debug Alert", "message": "Developer-triggered alert for HA/mobile relay."},
                "event": {"event_type": "debug_external_alert", "summary": "Debug external alert", "attributes": {"target": "ha"}},
                "data": {"debug": True, "bridge_expected": "hexe-notify/ha"},
            }
        )
        self._log_result("event", event_result)

        state_result = await self._publisher.publish_internal_state(
            {
                "source": {"kind": "core", "id": "hexe-core", "component": "debug", "host": hostname, "user": username},
                "targets": {"broadcast": True},
                "delivery": {"severity": "success", "priority": "normal", "dedupe_key": "dev-state"},
                "content": {"title": f"{naming.platform_short()} Debug State", "message": "Developer-triggered state notification."},
                "state": {"state_type": "debug_flow", "status": "ready", "current": "ready"},
                "data": {"debug": True},
            },
            retain=True,
        )
        self._log_result("state", state_result)
        return [popup_result, event_result, state_result]

    def _log_result(self, notification_type: str, result: dict[str, Any]) -> None:
        level = logging.INFO if bool(result.get("ok")) else logging.WARNING
        self._log.log(
            level,
            "debug_notification_emitted type=%s topic=%s ok=%s message_id=%s result=%s",
            notification_type,
            result.get("topic"),
            bool(result.get("ok")),
            result.get("message_id"),
            result,
        )

    def _current_user(self) -> str | None:
        try:
            user = getpass.getuser().strip()
        except Exception:
            return None
        return user or None

from __future__ import annotations

import getpass
import logging
import socket
from typing import Any

from .notification_publisher import CoreNotificationPublisher


class CoreStartupNotificationProducer:
    def __init__(self, publisher: CoreNotificationPublisher, *, core_version: str = "0.1.0") -> None:
        self._publisher = publisher
        self._core_version = str(core_version or "0.1.0").strip() or "0.1.0"
        self._log = logging.getLogger("synthia.core.notifications")

    async def emit_startup_notifications(self) -> list[dict[str, Any]]:
        hostname = socket.gethostname().strip() or "localhost"
        username = self._current_user()
        targets = {"hosts": [hostname]}
        if username:
            targets["users"] = [username]

        source = {
            "kind": "core",
            "id": "synthia-core",
            "component": "startup",
            "label": "Synthia Core",
            "host": hostname,
            "user": username,
            "metadata": {"version": self._core_version},
        }
        common_data = {"smoke_test": True, "core_version": self._core_version}

        popup_result = await self._publisher.publish_internal_popup(
            {
                "source": source,
                "targets": targets,
                "delivery": {
                    "severity": "success",
                    "priority": "normal",
                    "ttl_seconds": 300,
                    "dedupe_key": "core-startup-popup",
                },
                "content": {
                    "title": "Synthia Core Ready",
                    "message": "Core startup completed and notification publishing is active.",
                },
                "event": {
                    "event_type": "core_startup_popup",
                    "summary": "Startup popup smoke test",
                },
                "data": common_data,
            }
        )
        self._log_result("popup", popup_result)

        event_result = await self._publisher.publish_internal_event(
            {
                "source": source,
                "targets": {"broadcast": True, "hosts": [hostname]},
                "delivery": {
                    "severity": "info",
                    "priority": "normal",
                    "dedupe_key": "core-startup-event",
                },
                "content": {
                    "title": "Core startup complete",
                    "message": "Startup event emitted for notification pipeline smoke testing.",
                },
                "event": {
                    "event_type": "core_startup_complete",
                    "action": "startup_complete",
                    "summary": "Core startup sequence finished",
                    "attributes": {"host": hostname},
                },
                "data": common_data,
            }
        )
        self._log_result("event", event_result)

        state_result = await self._publisher.publish_internal_state(
            {
                "source": source,
                "targets": {"broadcast": True, "hosts": [hostname]},
                "delivery": {
                    "severity": "success",
                    "priority": "normal",
                    "dedupe_key": "core-startup-state",
                },
                "content": {
                    "title": "Core runtime ready",
                    "message": "Core runtime state published after startup.",
                },
                "state": {
                    "state_type": "core_runtime",
                    "status": "ready",
                    "current": "ready",
                    "attributes": {"host": hostname, "version": self._core_version},
                },
                "data": common_data,
            },
            retain=True,
        )
        self._log_result("state", state_result)
        return [popup_result, event_result, state_result]

    def _log_result(self, notification_type: str, result: dict[str, Any]) -> None:
        level = logging.INFO if bool(result.get("ok")) else logging.WARNING
        self._log.log(
            level,
            "startup_notification_emitted type=%s topic=%s ok=%s message_id=%s result=%s",
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

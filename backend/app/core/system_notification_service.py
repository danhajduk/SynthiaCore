from __future__ import annotations

import logging
import socket
from typing import Any

from app.system.platform_identity import default_platform_naming
from .notification_publisher import CoreNotificationPublisher


class CoreSystemNotificationService:
    def __init__(self, publisher: CoreNotificationPublisher, *, core_version: str = "0.1.0") -> None:
        self._publisher = publisher
        self._core_version = str(core_version or "0.1.0").strip() or "0.1.0"
        self._log = logging.getLogger("synthia.core.notifications")

    async def emit_system_online(self, *, component: str = "system", message: str | None = None) -> dict[str, Any]:
        naming = default_platform_naming()
        hostname = socket.gethostname().strip() or "localhost"
        payload = {
            "source": self._source(component=component, host=hostname),
            "targets": {"external": ["ha"]},
            "delivery": {
                "severity": "success",
                "priority": "normal",
                "urgency": "notification",
                "dedupe_key": f"core-{component}-online",
            },
            "content": {
                "title": f"{naming.core()} Online",
                "message": message or f"{naming.core()} is online.",
            },
            "event": {
                "event_type": "core_system_online",
                "action": "online",
                "summary": f"{naming.core()} online",
                "attributes": {"component": component, "host": hostname},
            },
            "data": {"core_version": self._core_version, "component": component, "host": hostname},
        }
        return await self._emit_event(notification_type="online", component=component, payload=payload)

    async def emit_system_warning(
        self,
        *,
        component: str,
        message: str,
        dedupe_key: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        naming = default_platform_naming()
        hostname = socket.gethostname().strip() or "localhost"
        payload = {
            "source": self._source(component=component, host=hostname),
            "targets": {"external": ["ha"]},
            "delivery": {
                "severity": "warning",
                "priority": "high",
                "urgency": "actions_needed",
                "dedupe_key": dedupe_key,
            },
            "content": {
                "title": f"{naming.core()} Warning",
                "message": message,
            },
            "event": {
                "event_type": "core_system_warning",
                "action": "warning",
                "summary": message,
                "attributes": {"component": component, "host": hostname},
            },
            "data": {"core_version": self._core_version, "component": component, "host": hostname, **(data or {})},
        }
        return await self._emit_event(notification_type="warning", component=component, payload=payload)

    async def emit_system_error(
        self,
        *,
        component: str,
        message: str,
        dedupe_key: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        naming = default_platform_naming()
        hostname = socket.gethostname().strip() or "localhost"
        payload = {
            "source": self._source(component=component, host=hostname),
            "targets": {"external": ["ha"]},
            "delivery": {
                "severity": "error",
                "priority": "urgent",
                "urgency": "urgent",
                "dedupe_key": dedupe_key,
            },
            "content": {
                "title": f"{naming.core()} Error",
                "message": message,
            },
            "event": {
                "event_type": "core_system_error",
                "action": "error",
                "summary": message,
                "attributes": {"component": component, "host": hostname},
            },
            "data": {"core_version": self._core_version, "component": component, "host": hostname, **(data or {})},
        }
        return await self._emit_event(notification_type="error", component=component, payload=payload)

    async def _emit_event(self, *, notification_type: str, component: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self._publisher.publish_internal_event(payload)
        level = logging.INFO if bool(result.get("ok")) else logging.WARNING
        self._log.log(
            level,
            "core_system_notification_emitted type=%s component=%s topic=%s ok=%s message_id=%s result=%s",
            notification_type,
            component,
            result.get("topic"),
            bool(result.get("ok")),
            result.get("message_id"),
            result,
        )
        return result

    def _source(self, *, component: str, host: str) -> dict[str, Any]:
        naming = default_platform_naming()
        return {
            "kind": "core",
            "id": "hexe-core",
            "component": component,
            "label": naming.core(),
            "host": host,
            "metadata": {"version": self._core_version},
        }

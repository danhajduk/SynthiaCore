from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from .notification_publisher import CoreNotificationPublisher
from .notifications import (
    NODE_NOTIFICATION_REQUEST_TOPIC_FILTER,
    NodeNotificationProxyStatus,
    NodeNotificationRequest,
    NodeNotificationResult,
    NotificationMessage,
    NotificationSource,
    NotificationSourceKind,
    node_notification_result_topic,
)


class NodeNotificationProxyService:
    def __init__(self, publisher: CoreNotificationPublisher, mqtt_manager, state_store) -> None:
        self._publisher = publisher
        self._mqtt = mqtt_manager
        self._state_store = state_store
        self._log = logging.getLogger("synthia.core.notifications")
        self._listener_ids: list[str] = []

    async def start(self) -> None:
        if self._listener_ids:
            return
        self._listener_ids.append(
            self._mqtt.register_message_listener(
                topic_filter=NODE_NOTIFICATION_REQUEST_TOPIC_FILTER,
                callback=self._handle_runtime_message,
            )
        )
        self._log.info("node_notification_proxy_started topic_filter=%s", NODE_NOTIFICATION_REQUEST_TOPIC_FILTER)

    async def stop(self) -> None:
        for listener_id in list(self._listener_ids):
            self._mqtt.unregister_message_listener(listener_id)
        self._listener_ids.clear()

    async def _handle_runtime_message(self, topic: str, payload: dict[str, Any], retained: bool) -> None:
        node_id = self._topic_node_id(topic)
        if not node_id:
            return
        if retained:
            result = self._rejected_result(
                node_id=node_id,
                request_id=str(payload.get("request_id") or ""),
                error="retained_requests_not_supported",
                requested_external_targets=list((payload.get("targets") or {}).get("external") or []),
            )
            await self._publish_result(node_id=node_id, result=result)
            return
        try:
            request = NodeNotificationRequest.model_validate(payload)
        except ValidationError as exc:
            self._log.warning("node_notification_proxy_rejected topic=%s reason=invalid error=%s", topic, exc.errors())
            result = self._rejected_result(
                node_id=node_id,
                request_id=str(payload.get("request_id") or ""),
                error="notification_request_invalid",
                requested_external_targets=list((payload.get("targets") or {}).get("external") or []),
            )
            await self._publish_result(node_id=node_id, result=result)
            return

        result = await self._process_request(node_id=node_id, request=request)
        await self._publish_result(node_id=node_id, result=result)

    async def _process_request(self, *, node_id: str, request: NodeNotificationRequest) -> NodeNotificationResult:
        if request.node_id and request.node_id != node_id:
            return self._rejected_result(
                node_id=node_id,
                request_id=request.request_id,
                error="node_id_topic_mismatch",
                requested_external_targets=list(request.targets.external),
            )
        state = await self._state_store.get_state()
        principal = state.principals.get(f"node:{node_id}")
        if principal is None or principal.principal_type != "synthia_node" or principal.status in {"revoked", "expired"}:
            return self._rejected_result(
                node_id=node_id,
                request_id=request.request_id,
                error="node_principal_unavailable",
                requested_external_targets=list(request.targets.external),
            )

        source_hint = request.source
        source = NotificationSource(
            kind=NotificationSourceKind.NODE,
            id=node_id,
            component=(source_hint.component if source_hint is not None else None),
            label=(source_hint.label if source_hint is not None else None),
            metadata={
                **(source_hint.metadata if source_hint is not None else {}),
                "node_principal_id": principal.principal_id,
                "request_id": request.request_id,
            },
        )
        message = NotificationMessage(
            source=source,
            targets=request.targets,
            delivery=request.delivery,
            content=request.content,
            event=request.event,
            state=request.state,
            data=request.data,
        )
        if request.kind.value == "popup":
            publish_result = await self._publisher.publish_internal_popup(message)
        elif request.kind.value == "state":
            publish_result = await self._publisher.publish_internal_state(message, retain=bool(request.retain))
        else:
            publish_result = await self._publisher.publish_internal_event(message)
        if not bool(publish_result.get("ok")):
            self._log.warning(
                "node_notification_proxy_rejected node_id=%s request_id=%s reason=publish_failed result=%s",
                node_id,
                request.request_id,
                publish_result,
            )
            return self._rejected_result(
                node_id=node_id,
                request_id=request.request_id,
                error=str(publish_result.get("error") or "notification_publish_failed"),
                requested_external_targets=list(request.targets.external),
            )
        self._log.info(
            "node_notification_proxy_accepted node_id=%s request_id=%s internal_topic=%s message_id=%s",
            node_id,
            request.request_id,
            publish_result.get("topic"),
            publish_result.get("message_id"),
        )
        return NodeNotificationResult(
            request_id=request.request_id,
            node_id=node_id,
            status=NodeNotificationProxyStatus.ACCEPTED,
            accepted=True,
            notification_id=str(publish_result.get("message_id") or ""),
            internal_topic=str(publish_result.get("topic") or ""),
            requested_external_targets=list(request.targets.external),
        )

    async def _publish_result(self, *, node_id: str, result: NodeNotificationResult) -> None:
        topic = node_notification_result_topic(node_id)
        try:
            await self._mqtt.publish(topic=topic, payload=result.model_dump(mode="json", exclude_none=True), retain=False, qos=1)
        except Exception:
            self._log.exception("node_notification_proxy_result_publish_failed node_id=%s topic=%s", node_id, topic)

    @staticmethod
    def _rejected_result(
        *,
        node_id: str,
        request_id: str,
        error: str,
        requested_external_targets: list[str],
    ) -> NodeNotificationResult:
        return NodeNotificationResult(
            request_id=(request_id or "unknown"),
            node_id=node_id,
            status=NodeNotificationProxyStatus.REJECTED,
            accepted=False,
            error=error,
            requested_external_targets=[str(item).strip() for item in requested_external_targets if str(item).strip()],
        )

    @staticmethod
    def _topic_node_id(topic: str) -> str | None:
        parts = [part for part in str(topic or "").split("/") if part]
        if len(parts) == 5 and parts[0] == "hexe" and parts[1] == "nodes" and parts[3] == "notify" and parts[4] == "request":
            return str(parts[2]).strip() or None
        return None

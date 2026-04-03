from __future__ import annotations

import unittest
from typing import Any

from app.core import NodeNotificationProxyService
from app.system.mqtt.integration_models import MqttIntegrationState, MqttPrincipal


class _FakeMqttManager:
    def __init__(self) -> None:
        self.listeners: dict[str, tuple[str, Any]] = {}
        self.counter = 0
        self.publish_calls: list[dict[str, Any]] = []

    def register_message_listener(self, *, topic_filter: str, callback):
        self.counter += 1
        listener_id = f"listener-{self.counter}"
        self.listeners[listener_id] = (topic_filter, callback)
        return listener_id

    def unregister_message_listener(self, listener_id: str) -> bool:
        return self.listeners.pop(listener_id, None) is not None

    async def publish(self, topic: str, payload: dict[str, Any], retain: bool = True, qos: int = 1) -> dict[str, Any]:
        self.publish_calls.append({"topic": topic, "payload": payload, "retain": retain, "qos": qos})
        return {"ok": True, "topic": topic, "rc": 0}


class _FakeNotificationPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def publish_internal_popup(self, message, *, qos: int = 1) -> dict[str, Any]:
        payload = message.to_payload(exclude_none=True)
        self.calls.append(("popup", payload, {"qos": qos}))
        return {"ok": True, "topic": "hexe/notify/internal/popup", "message_id": "popup-1"}

    async def publish_internal_event(self, message, *, qos: int = 1) -> dict[str, Any]:
        payload = message.to_payload(exclude_none=True)
        self.calls.append(("event", payload, {"qos": qos}))
        return {"ok": True, "topic": "hexe/notify/internal/event", "message_id": "event-1"}

    async def publish_internal_state(self, message, *, qos: int = 1, retain: bool = False) -> dict[str, Any]:
        payload = message.to_payload(exclude_none=True)
        self.calls.append(("state", payload, {"qos": qos, "retain": retain}))
        return {"ok": True, "topic": "hexe/notify/internal/state", "message_id": "state-1"}


class _FakeStateStore:
    def __init__(self, state: MqttIntegrationState) -> None:
        self._state = state

    async def get_state(self) -> MqttIntegrationState:
        return self._state


class TestNotificationProxy(unittest.IsolatedAsyncioTestCase):
    def _state(self) -> MqttIntegrationState:
        return MqttIntegrationState(
            principals={
                "node:node-123": MqttPrincipal(
                    principal_id="node:node-123",
                    principal_type="synthia_node",
                    status="active",
                    logical_identity="node-123",
                    linked_node_id="node-123",
                    username="hn_node-123",
                    publish_topics=["hexe/nodes/node-123/#"],
                    subscribe_topics=["hexe/bootstrap/core", "hexe/nodes/node-123/#"],
                )
            }
        )

    def _request(self, **overrides) -> dict[str, Any]:
        payload = {
            "request_id": "req-1",
            "kind": "event",
            "targets": {"external": ["ha"]},
            "delivery": {"severity": "warning", "priority": "high", "dedupe_key": "node-alert"},
            "source": {"component": "detector", "metadata": {"camera": "front"}},
            "content": {"title": "Motion", "message": "Front camera detected motion."},
            "event": {"event_type": "motion_detected", "summary": "Motion detected"},
            "data": {"confidence": 0.98},
        }
        payload.update(overrides)
        return payload

    async def test_proxy_registers_node_notification_request_filter(self) -> None:
        mqtt = _FakeMqttManager()
        proxy = NodeNotificationProxyService(_FakeNotificationPublisher(), mqtt, _FakeStateStore(self._state()))

        await proxy.start()

        filters = [item[0] for item in mqtt.listeners.values()]
        self.assertEqual(filters, ["hexe/nodes/+/notify/request"])

    async def test_proxy_accepts_valid_node_request_and_publishes_result(self) -> None:
        mqtt = _FakeMqttManager()
        publisher = _FakeNotificationPublisher()
        proxy = NodeNotificationProxyService(publisher, mqtt, _FakeStateStore(self._state()))

        await proxy._handle_runtime_message("hexe/nodes/node-123/notify/request", self._request(), False)

        self.assertEqual(len(publisher.calls), 1)
        kind, payload, _meta = publisher.calls[0]
        self.assertEqual(kind, "event")
        self.assertEqual(payload["source"]["kind"], "node")
        self.assertEqual(payload["source"]["id"], "node-123")
        self.assertEqual(payload["source"]["component"], "detector")
        self.assertEqual(payload["targets"]["external"], ["ha"])
        self.assertEqual(mqtt.publish_calls[-1]["topic"], "hexe/nodes/node-123/notify/result")
        self.assertTrue(mqtt.publish_calls[-1]["payload"]["accepted"])
        self.assertEqual(mqtt.publish_calls[-1]["payload"]["internal_topic"], "hexe/notify/internal/event")

    async def test_proxy_rejects_node_id_mismatch(self) -> None:
        mqtt = _FakeMqttManager()
        publisher = _FakeNotificationPublisher()
        proxy = NodeNotificationProxyService(publisher, mqtt, _FakeStateStore(self._state()))

        await proxy._handle_runtime_message(
            "hexe/nodes/node-123/notify/request",
            self._request(node_id="other-node"),
            False,
        )

        self.assertEqual(publisher.calls, [])
        self.assertFalse(mqtt.publish_calls[-1]["payload"]["accepted"])
        self.assertEqual(mqtt.publish_calls[-1]["payload"]["error"], "node_id_topic_mismatch")

    async def test_proxy_rejects_unknown_node_principal(self) -> None:
        mqtt = _FakeMqttManager()
        publisher = _FakeNotificationPublisher()
        proxy = NodeNotificationProxyService(publisher, mqtt, _FakeStateStore(MqttIntegrationState()))

        await proxy._handle_runtime_message("hexe/nodes/node-123/notify/request", self._request(), False)

        self.assertEqual(publisher.calls, [])
        self.assertFalse(mqtt.publish_calls[-1]["payload"]["accepted"])
        self.assertEqual(mqtt.publish_calls[-1]["payload"]["error"], "node_principal_unavailable")

    async def test_proxy_allows_retained_state_requests_only(self) -> None:
        mqtt = _FakeMqttManager()
        publisher = _FakeNotificationPublisher()
        proxy = NodeNotificationProxyService(publisher, mqtt, _FakeStateStore(self._state()))

        await proxy._handle_runtime_message(
            "hexe/nodes/node-123/notify/request",
            self._request(
                kind="state",
                retain=True,
                state={"state_type": "camera_motion", "status": "active", "current": "active"},
                event=None,
            ),
            False,
        )

        self.assertEqual(publisher.calls[0][0], "state")
        self.assertTrue(publisher.calls[0][2]["retain"])


if __name__ == "__main__":
    unittest.main()

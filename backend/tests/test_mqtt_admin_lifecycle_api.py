import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.addons.models import AddonMeta, BackendAddon, RegisteredAddon
from app.addons.registry import AddonRegistry
from app.system.auth import ServiceTokenKeyStore
from app.system.mqtt.acl_compiler import MqttAclCompiler
from app.system.mqtt.approval import MqttRegistrationApprovalService
from app.system.mqtt.credential_store import MqttCredentialStore
from app.system.mqtt.integration_state import MqttIntegrationStateStore
from app.system.mqtt.router import build_mqtt_router


class _FakeSettingsStore:
    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    async def get(self, key: str):
        return self._data.get(key)


class _FakeMqttManager:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []

    async def status(self):
        return {"ok": True, "enabled": True, "connected": True, "last_message_at": None}

    async def restart(self):
        return None

    async def publish_test(self, topic: str | None = None, payload: dict | None = None):
        return {"ok": True, "topic": topic or "synthia/core/mqtt/info", "payload": payload or {}}

    async def publish(self, topic: str, payload: dict, retain: bool = True, qos: int = 1):
        self.published.append({"topic": topic, "payload": payload, "retain": retain, "qos": qos})
        return {"ok": True, "topic": topic, "rc": 0}

    def _core_info_payload(self) -> dict:
        return {"source": "synthia-core", "type": "core-mqtt-info"}

    async def debug_connection_config(self):
        return {
            "mode": "local",
            "host": "127.0.0.1",
            "port": 1883,
            "username": None,
            "password": None,
            "tls_enabled": False,
            "keepalive_s": 30,
        }

    async def topic_activity(self, *, limit: int = 500):
        return {
            "ok": True,
            "items": [
                {
                    "topic": "external/test/events",
                    "message_count": 3,
                    "retained_seen": False,
                    "sources": ["runtime_messages"],
                    "last_seen": "2026-03-11T00:00:00Z",
                }
            ],
        }


class _FakeRuntimeReconciler:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def reconcile_authority(self, *, reason: str):
        self.calls.append(reason)
        return None

    def reconciliation_status(self):
        return {"status": "ok"}

    def bootstrap_status(self):
        return {"published": True}

    def live_dir(self):
        return "/tmp"


class _FakeAuditStore:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    async def append_event(self, *, event_type: str, status: str, message: str | None = None, payload: dict | None = None):
        now = time.time()
        payload_obj = payload or {}
        actor_principal = str(
            payload_obj.get("actor_principal")
            or payload_obj.get("principal_id")
            or payload_obj.get("addon_id")
            or payload_obj.get("actor")
            or ""
        ).strip()
        action = str(payload_obj.get("action") or message or event_type or "").strip()
        target = str(payload_obj.get("target") or payload_obj.get("principal_id") or payload_obj.get("addon_id") or "").strip()
        self.items.append(
            {
                "event_type": event_type,
                "status": status,
                "message": message,
                "payload": payload_obj,
                "created_at": str(now),
                "actor_principal": actor_principal or None,
                "action": action or None,
                "target": target or None,
                "result": status,
                "timestamp": str(now),
            }
        )

    async def list_events(self, limit: int = 100, *, principal: str | None = None, action: str | None = None):
        principal_filter = str(principal or "").strip().lower()
        action_filter = str(action or "").strip().lower()
        out: list[dict[str, object]] = []
        for item in reversed(self.items):
            actor = str(item.get("actor_principal") or "").lower()
            target = str(item.get("target") or "").lower()
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            principal_payload = str(payload.get("principal_id") or payload.get("addon_id") or "").lower()
            if principal_filter and principal_filter not in actor and principal_filter not in target and principal_filter not in principal_payload:
                continue
            item_action = str(item.get("action") or "").lower()
            event_type = str(item.get("event_type") or "").lower()
            if action_filter and action_filter not in item_action and action_filter not in event_type:
                continue
            out.append(item)
            if len(out) >= max(1, min(1000, int(limit))):
                break
        return out


class TestMqttAdminLifecycleApi(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(os.environ, {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False)
        self.env_patch.start()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.settings = _FakeSettingsStore()
        self.key_store = ServiceTokenKeyStore(self.settings)
        self.state_store = MqttIntegrationStateStore(str(Path(self.tmpdir.name) / "mqtt_state.json"))
        self.credential_store = MqttCredentialStore(str(Path(self.tmpdir.name) / "mqtt_credentials.json"))
        self.runtime = _FakeRuntimeReconciler()
        self.audit = _FakeAuditStore()
        self.registry = AddonRegistry(
            addons={
                "vision": BackendAddon(
                    meta=AddonMeta(id="vision", name="Vision", version="1.0.0"),
                    router=APIRouter(),
                )
            },
            errors={},
            enabled={"vision": True},
            registered={
                "mqtt": RegisteredAddon(
                    id="mqtt",
                    name="MQTT",
                    version="1.0.0",
                    base_url="http://mqtt-addon.local:9100",
                )
            },
        )
        self.approval = MqttRegistrationApprovalService(
            registry=self.registry,
            state_store=self.state_store,
            runtime_reconcile_hook=self.runtime.reconcile_authority,
            audit_store=self.audit,
            credential_rotate_hook=self.credential_store.rotate_principal,
        )
        self.manager = _FakeMqttManager()
        app = FastAPI()
        app.include_router(
            build_mqtt_router(
                self.manager,
                self.registry,
                self.state_store,
                self.key_store,
                approval_service=self.approval,
                acl_compiler=MqttAclCompiler(),
                credential_store=self.credential_store,
                runtime_reconciler=self.runtime,
                audit_store=self.audit,
            ),
            prefix="/api/system",
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()
        self.env_patch.stop()

    def test_principal_actions_and_generic_user_lifecycle(self) -> None:
        create = self.client.post(
            "/api/system/mqtt/generic-users",
            headers={"X-Admin-Token": "test-token"},
            json={
                "principal_id": "user:guest1",
                "logical_identity": "guest1",
                "username": "guest1",
                "publish_topics": ["devices/guest1/state"],
                "subscribe_topics": ["devices/guest1/cmd"],
            },
        )
        self.assertEqual(create.status_code, 200, create.text)
        self.assertTrue(create.json()["ok"])

        grants = self.client.patch(
            "/api/system/mqtt/generic-users/user:guest1/grants",
            headers={"X-Admin-Token": "test-token"},
            json={
                "publish_topics": ["devices/guest1/state/#"],
                "subscribe_topics": ["devices/guest1/cmd/#"],
            },
        )
        self.assertEqual(grants.status_code, 200, grants.text)
        self.assertTrue(grants.json()["ok"])

        probation = self.client.post(
            "/api/system/mqtt/principals/user:guest1/actions/probation",
            headers={"X-Admin-Token": "test-token"},
            json={"reason": "suspicious"},
        )
        self.assertEqual(probation.status_code, 200, probation.text)
        self.assertEqual(probation.json()["principal"]["status"], "probation")

        promoted = self.client.post(
            "/api/system/mqtt/principals/user:guest1/actions/promote",
            headers={"X-Admin-Token": "test-token"},
            json={"reason": "verified"},
        )
        self.assertEqual(promoted.status_code, 200, promoted.text)
        self.assertEqual(promoted.json()["principal"]["status"], "active")

        revoke = self.client.post(
            "/api/system/mqtt/generic-users/user:guest1/revoke",
            headers={"X-Admin-Token": "test-token"},
            json={"reason": "manual"},
        )
        self.assertEqual(revoke.status_code, 200, revoke.text)
        self.assertEqual(revoke.json()["principal"]["status"], "revoked")

    def test_debug_subscribe_and_unsubscribe_endpoints(self) -> None:
        class _FakeDebugClient:
            def __init__(self, *args, **kwargs) -> None:
                self.on_message = None

            def username_pw_set(self, username, password=None):
                return None

            def tls_set(self):
                return None

            def connect_async(self, host, port, keepalive):
                return None

            def loop_start(self):
                return None

            def subscribe(self, topic, qos=0):
                if callable(self.on_message):
                    class _Msg:
                        topic = "synthia/addons/vision/event/status"
                        payload = b'{"value":42}'
                        retain = False
                        qos = 0

                    self.on_message(self, None, _Msg())
                return (0, 1)

            def disconnect(self):
                return None

            def loop_stop(self):
                return None

        with patch("paho.mqtt.client.Client", _FakeDebugClient):
            created = self.client.post(
                "/api/system/debug/subscribe",
                headers={"X-Admin-Token": "test-token"},
                json={"topic_filter": "synthia/#", "qos": 0, "timeout_s": 60},
            )
            self.assertEqual(created.status_code, 200, created.text)
            payload = created.json()
            self.assertTrue(payload["ok"])
            sub_id = payload["subscription_id"]

            messages = self.client.get(
                f"/api/system/debug/subscribe/{sub_id}/messages",
                headers={"X-Admin-Token": "test-token"},
            )
            self.assertEqual(messages.status_code, 200, messages.text)
            self.assertTrue(messages.json()["ok"])
            self.assertIsInstance(messages.json()["items"], list)
            self.assertTrue(messages.json()["items"])
            first = messages.json()["items"][0]
            self.assertEqual(first["source_principal"], "addon:vision")
            self.assertIn("payload_preview", first)
            self.assertIn("timestamp", first)

            stopped = self.client.post(
                "/api/system/debug/unsubscribe",
                headers={"X-Admin-Token": "test-token"},
                json={"subscription_id": sub_id},
            )
            self.assertEqual(stopped.status_code, 200, stopped.text)
            self.assertTrue(stopped.json()["ok"])

            missing = self.client.get(
                f"/api/system/debug/subscribe/{sub_id}/messages",
                headers={"X-Admin-Token": "test-token"},
            )
            self.assertEqual(missing.status_code, 404, missing.text)

    def test_debug_publish_blocks_reserved_topics_and_allows_external(self) -> None:
        blocked = self.client.post(
            "/api/system/debug/publish",
            headers={"X-Admin-Token": "test-token"},
            json={"topic": "synthia/runtime/health", "payload": {"x": 1}, "qos": 0, "retain": False},
        )
        self.assertEqual(blocked.status_code, 400, blocked.text)
        self.assertIn("reserved_topic_publish_forbidden", blocked.text)
        self.assertTrue(
            any(
                str(item.get("event_type")) == "mqtt_runtime_control"
                and str(item.get("message")) == "reserved_topic_publish_forbidden"
                for item in self.audit.items
            )
        )

        allowed = self.client.post(
            "/api/system/debug/publish",
            headers={"X-Admin-Token": "test-token"},
            json={"topic": "external/debug/events", "payload": {"hello": "world"}, "qos": 1, "retain": True},
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertTrue(allowed.json()["ok"])
        self.assertEqual(allowed.json()["topic"], "external/debug/events")
        self.assertEqual(len(self.manager.published), 1)

    def test_runtime_config_alias_endpoint(self) -> None:
        config = self.client.get("/api/system/runtime/config", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(config.status_code, 200, config.text)
        payload = config.json()
        self.assertTrue(payload["ok"])
        self.assertIn("files", payload)
        self.assertIsInstance(payload["files"], dict)

    def test_runtime_topics_endpoint(self) -> None:
        topics = self.client.get("/api/system/runtime/topics", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(topics.status_code, 200, topics.text)
        payload = topics.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["items"])
        self.assertEqual(payload["items"][0]["topic"], "external/test/events")

    def test_topic_scope_rejection_writes_violation_audit(self) -> None:
        rejected = self.client.post(
            "/api/system/mqtt/registrations/approve",
            headers={"X-Admin-Token": "test-token"},
            json={
                "addon_id": "vision",
                "access_mode": "gateway",
                "publish_topics": ["synthia/runtime/health"],
                "subscribe_topics": ["synthia/addons/vision/command/#"],
                "capabilities": {},
            },
        )
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertFalse(rejected.json()["ok"])
        self.assertTrue(
            any(
                str(item.get("event_type")) == "mqtt_topic_violation"
                and str(item.get("message")) == "addon_scope_rejected"
                for item in self.audit.items
            )
        )

    def test_rotate_credentials_and_effective_access_inspection(self) -> None:
        created = asyncio.run(
            self.approval.create_or_update_generic_user(
                principal_id="user:guest2",
                logical_identity="guest2",
                username="guest2",
                publish_topics=["devices/guest2/state"],
                subscribe_topics=["devices/guest2/cmd"],
            )
        )
        self.assertTrue(created["ok"])
        state = asyncio.run(self.state_store.get_state())
        self.credential_store.render_password_file(state)

        rotate = self.client.post(
            "/api/system/mqtt/generic-users/user:guest2/rotate-credentials",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(rotate.status_code, 200, rotate.text)
        self.assertTrue(rotate.json()["rotated"])

        inspect_access = self.client.get(
            "/api/system/mqtt/generic-users/user:guest2/effective-access",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(inspect_access.status_code, 200, inspect_access.text)
        payload = inspect_access.json()["effective_access"]
        self.assertTrue(payload["generic_non_reserved_only"])
        self.assertIn("synthia/core/#", payload["reserved_prefix_denies"])

        inspect_debug = self.client.get(
            "/api/system/mqtt/debug/effective-access/user:guest2",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(inspect_debug.status_code, 200, inspect_debug.text)
        self.assertEqual(inspect_debug.json()["principal_id"], "user:guest2")

        rotate_alias = self.client.post(
            "/api/system/mqtt/users/user:guest2/rotate",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(rotate_alias.status_code, 200, rotate_alias.text)
        self.assertTrue(rotate_alias.json()["rotated"])
        self.assertTrue(rotate_alias.json().get("password"))

    def test_principal_alias_endpoints_cover_details_permissions_last_seen_and_actions(self) -> None:
        created = self.client.post(
            "/api/system/mqtt/users",
            headers={"X-Admin-Token": "test-token"},
            json={
                "username": "aliasuser",
                "password": "generated",
                "topic_prefix": "external/aliasuser",
                "access_mode": "private",
                "allowed_topics": [],
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        principal_id = "user:aliasuser"

        details = self.client.get(
            f"/api/system/principals/{principal_id}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(details.status_code, 200, details.text)
        self.assertEqual(details.json()["principal"]["principal_id"], principal_id)

        permissions = self.client.get(
            f"/api/system/principals/{principal_id}/permissions",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(permissions.status_code, 200, permissions.text)
        self.assertEqual(permissions.json()["permissions"]["principal_id"], principal_id)
        self.assertTrue(permissions.json()["permissions"]["publish_topics"])

        last_seen = self.client.get(
            f"/api/system/principals/{principal_id}/last_seen",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(last_seen.status_code, 200, last_seen.text)
        self.assertEqual(last_seen.json()["last_seen"]["principal_id"], principal_id)

        disable = self.client.post(
            f"/api/system/principals/{principal_id}/disable",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(disable.status_code, 200, disable.text)
        self.assertEqual(disable.json()["principal"]["status"], "probation")

        activate = self.client.post(
            f"/api/system/principals/{principal_id}/activate",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(activate.status_code, 200, activate.text)
        self.assertEqual(activate.json()["principal"]["status"], "active")

        rotate = self.client.post(
            f"/api/system/principals/{principal_id}/rotate_password",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(rotate.status_code, 200, rotate.text)
        self.assertTrue(rotate.json()["rotated"])

        revoke = self.client.post(
            f"/api/system/principals/{principal_id}/revoke",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(revoke.status_code, 200, revoke.text)
        self.assertEqual(revoke.json()["principal"]["status"], "revoked")

        deleted = self.client.delete(
            f"/api/system/principals/{principal_id}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()["ok"])

    def test_users_api_creates_external_scoped_generic_user(self) -> None:
        created = self.client.post(
            "/api/system/mqtt/users",
            headers={"X-Admin-Token": "test-token"},
            json={
                "username": "HomeAssistant",
                "password": "generated",
                "topic_prefix": "external/homeassistant",
                "access_mode": "custom",
                "allowed_publish_topics": ["external/homeassistant/controls/#"],
                "allowed_subscribe_topics": ["external/homeassistant/sensors/#"],
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        payload = created.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["username"], "homeassistant")
        self.assertEqual(payload["topic_prefix"], "external/homeassistant")
        self.assertEqual(payload["scope"], "external/homeassistant/controls/#")
        self.assertEqual(payload["access_mode"], "custom")
        self.assertEqual(len(payload["allowed_topics"]), 2)
        self.assertEqual(payload["allowed_publish_topics"], ["external/homeassistant/controls/#"])
        self.assertEqual(payload["allowed_subscribe_topics"], ["external/homeassistant/sensors/#"])
        self.assertEqual(payload["password_mode"], "generated")
        self.assertTrue(payload.get("password"))

        state = asyncio.run(self.state_store.get_state())
        principal = state.principals.get("user:homeassistant")
        self.assertIsNotNone(principal)
        self.assertEqual(principal.principal_type, "generic_user")
        self.assertEqual(principal.topic_prefix, "external/homeassistant")
        self.assertEqual(principal.access_mode, "custom")
        self.assertEqual(principal.allowed_publish_topics, ["external/homeassistant/controls/#"])
        self.assertEqual(principal.allowed_subscribe_topics, ["external/homeassistant/sensors/#"])
        self.assertIn("external/homeassistant/sensors/#", principal.allowed_topics)

        acl = MqttAclCompiler().compile(state).acl_text
        self.assertIn("user homeassistant", acl)
        self.assertIn("topic write external/homeassistant/controls/#", acl)
        self.assertIn("topic read external/homeassistant/sensors/#", acl)
        self.assertIn("topic deny synthia/#", acl)

        edited = self.client.patch(
            "/api/system/mqtt/users/user:homeassistant",
            headers={"X-Admin-Token": "test-token"},
            json={"topic_prefix": "external/homeassistant-v2", "access_mode": "private"},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertTrue(edited.json()["ok"])
        state_after_edit = asyncio.run(self.state_store.get_state())
        self.assertEqual(state_after_edit.principals["user:homeassistant"].topic_prefix, "external/homeassistant-v2")
        self.assertEqual(state_after_edit.principals["user:homeassistant"].access_mode, "private")

        deleted = self.client.delete(
            "/api/system/mqtt/users/user:homeassistant",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()["ok"])
        state_after_delete = asyncio.run(self.state_store.get_state())
        self.assertNotIn("user:homeassistant", state_after_delete.principals)

    def test_users_api_rejects_invalid_custom_topic_pattern(self) -> None:
        created = self.client.post(
            "/api/system/mqtt/users",
            headers={"X-Admin-Token": "test-token"},
            json={
                "username": "badtopic",
                "password": "generated",
                "topic_prefix": "external/badtopic",
                "access_mode": "custom",
                "allowed_publish_topics": ["external/badtopic/#/events"],
                "allowed_subscribe_topics": ["external/badtopic/events/#"],
            },
        )
        self.assertEqual(created.status_code, 400, created.text)
        self.assertIn("topic_pattern_invalid", str(created.json().get("detail")))

    def test_users_export_and_import_roundtrip(self) -> None:
        created = self.client.post(
            "/api/system/mqtt/users",
            headers={"X-Admin-Token": "test-token"},
            json={
                "username": "exportuser",
                "password": "generated",
                "topic_prefix": "external/exportuser",
                "access_mode": "custom",
                "allowed_publish_topics": ["external/exportuser/events/#"],
                "allowed_subscribe_topics": ["external/exportuser/cmd/#"],
            },
        )
        self.assertEqual(created.status_code, 200, created.text)

        exported = self.client.get("/api/system/mqtt/users/export", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(exported.status_code, 200, exported.text)
        exported_payload = exported.json()
        self.assertTrue(exported_payload["ok"])
        self.assertTrue(any(str(item.get("username")) == "exportuser" for item in exported_payload["items"]))

        imported = self.client.post(
            "/api/system/mqtt/users/import",
            headers={"X-Admin-Token": "test-token"},
            json={
                "items": [
                    {
                        "username": "importuser",
                        "topic_prefix": "external/importuser",
                        "access_mode": "custom",
                        "allowed_publish_topics": ["external/importuser/events/#"],
                        "allowed_subscribe_topics": ["external/importuser/cmd/#"],
                    }
                ]
            },
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertTrue(imported.json()["ok"])
        self.assertEqual(imported.json()["imported"], 1)
        state = asyncio.run(self.state_store.get_state())
        self.assertIn("user:importuser", state.principals)

    def test_noisy_client_manual_actions(self) -> None:
        created = asyncio.run(
            self.approval.create_or_update_generic_user(
                principal_id="user:guest3",
                logical_identity="guest3",
                username="guest3",
                publish_topics=["devices/guest3/state"],
                subscribe_topics=["devices/guest3/cmd"],
            )
        )
        self.assertTrue(created["ok"])

        watch = self.client.post(
            "/api/system/mqtt/noisy-clients/user:guest3/actions/mark_watch",
            headers={"X-Admin-Token": "test-token"},
            json={"reason": "manual_watch"},
        )
        self.assertEqual(watch.status_code, 200, watch.text)
        self.assertEqual(watch.json()["principal"]["noisy_state"], "watch")

        quarantine = self.client.post(
            "/api/system/mqtt/noisy-clients/user:guest3/actions/quarantine",
            headers={"X-Admin-Token": "test-token"},
            json={"reason": "manual_quarantine"},
        )
        self.assertEqual(quarantine.status_code, 200, quarantine.text)
        self.assertEqual(quarantine.json()["principal"]["noisy_state"], "blocked")
        self.assertEqual(quarantine.json()["principal"]["status"], "probation")

        effective = self.client.get(
            "/api/system/mqtt/debug/effective-access/user:guest3",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(effective.status_code, 200, effective.text)
        self.assertEqual(effective.json()["effective_access"]["publish_scopes"], [])
        self.assertEqual(effective.json()["effective_access"]["subscribe_scopes"], [])

        listed = self.client.get("/api/system/mqtt/noisy-clients", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(listed.status_code, 200, listed.text)
        ids = [item["principal_id"] for item in listed.json()["items"]]
        self.assertIn("user:guest3", ids)

        clear = self.client.post(
            "/api/system/mqtt/noisy-clients/user:guest3/actions/clear",
            headers={"X-Admin-Token": "test-token"},
            json={"reason": "manual_clear"},
        )
        self.assertEqual(clear.status_code, 200, clear.text)
        self.assertEqual(clear.json()["principal"]["noisy_state"], "normal")

    def test_runtime_noisy_mitigation_alias_endpoints(self) -> None:
        created = asyncio.run(
            self.approval.create_or_update_generic_user(
                principal_id="user:guest4",
                logical_identity="guest4",
                username="guest4",
                publish_topics=["devices/guest4/state"],
                subscribe_topics=["devices/guest4/cmd"],
            )
        )
        self.assertTrue(created["ok"])

        throttled = self.client.post(
            "/api/system/runtime/throttle",
            headers={"X-Admin-Token": "test-token"},
            json={"principal_id": "user:guest4", "reason": "rate_limit"},
        )
        self.assertEqual(throttled.status_code, 200, throttled.text)
        self.assertEqual(throttled.json()["principal"]["noisy_state"], "noisy")
        self.assertEqual(throttled.json()["principal"]["status"], "probation")

        disconnected = self.client.post(
            "/api/system/runtime/disconnect",
            headers={"X-Admin-Token": "test-token"},
            json={"principal_id": "user:guest4", "reason": "disconnect_test"},
        )
        self.assertEqual(disconnected.status_code, 200, disconnected.text)
        self.assertEqual(disconnected.json()["principal"]["noisy_state"], "blocked")

        blocked = self.client.post(
            "/api/system/runtime/block",
            headers={"X-Admin-Token": "test-token"},
            json={"principal_id": "user:guest4", "reason": "block_test"},
        )
        self.assertEqual(blocked.status_code, 200, blocked.text)
        self.assertEqual(blocked.json()["principal"]["status"], "revoked")

    def test_lifecycle_audit_events_emitted(self) -> None:
        created = self.client.post(
            "/api/system/mqtt/users",
            headers={"X-Admin-Token": "test-token"},
            json={"username": "audituser", "password": "generated", "topic_prefix": "external/audituser"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        rotate = self.client.post(
            "/api/system/mqtt/users/user:audituser/rotate",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(rotate.status_code, 200, rotate.text)
        revoke = self.client.post(
            "/api/system/mqtt/generic-users/user:audituser/revoke",
            headers={"X-Admin-Token": "test-token"},
            json={"reason": "audit_revoke"},
        )
        self.assertEqual(revoke.status_code, 200, revoke.text)
        event_types = [str(item.get("event_type")) for item in self.audit.items]
        self.assertIn("principal_created", event_types)
        self.assertIn("principal_activated", event_types)
        self.assertIn("password_rotated", event_types)
        self.assertIn("principal_revoked", event_types)

    def test_audit_endpoint_includes_enriched_fields_and_filters(self) -> None:
        created = self.client.post(
            "/api/system/mqtt/users",
            headers={"X-Admin-Token": "test-token"},
            json={"username": "filteruser", "password": "generated", "topic_prefix": "external/filteruser"},
        )
        self.assertEqual(created.status_code, 200, created.text)

        all_events = self.client.get("/api/system/mqtt/audit?limit=20", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(all_events.status_code, 200, all_events.text)
        items = all_events.json()["items"]
        self.assertTrue(items)
        self.assertIn("actor_principal", items[0])
        self.assertIn("action", items[0])
        self.assertIn("target", items[0])
        self.assertIn("result", items[0])
        self.assertIn("timestamp", items[0])

        principal_filtered = self.client.get(
            "/api/system/mqtt/audit?limit=20&principal=filteruser",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(principal_filtered.status_code, 200, principal_filtered.text)
        filtered_items = principal_filtered.json()["items"]
        self.assertTrue(filtered_items)
        self.assertTrue(
            any(
                "filteruser" in str(item.get("actor_principal") or "").lower()
                or "filteruser" in str(item.get("target") or "").lower()
                or "filteruser" in str((item.get("payload") or {}).get("principal_id") or "").lower()
                for item in filtered_items
            )
        )

        action_filtered = self.client.get(
            "/api/system/mqtt/audit?limit=20&action=principal_created",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(action_filtered.status_code, 200, action_filtered.text)
        self.assertTrue(action_filtered.json()["items"])

    def test_setup_summary_reports_missing_core_principals(self) -> None:
        summary = self.client.get("/api/system/mqtt/setup-summary", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(summary.status_code, 200, summary.text)
        payload = summary.json()
        self.assertIn("core_principals", payload)
        self.assertIn("missing", payload["core_principals"])
        self.assertIsInstance(payload["core_principals"]["missing"], list)


if __name__ == "__main__":
    unittest.main()

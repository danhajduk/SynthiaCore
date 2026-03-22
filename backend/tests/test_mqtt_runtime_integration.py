from __future__ import annotations

import asyncio
import json
import os
import tempfile
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
from app.system.mqtt.apply_pipeline import MqttApplyPipeline
from app.system.mqtt.authority_audit import MqttAuthorityAuditStore
from app.system.mqtt.config_renderer import MqttBrokerConfigRenderer
from app.system.mqtt.credential_store import MqttCredentialStore
from app.system.mqtt.integration_models import MqttCapabilityFlags, MqttRegistrationRequest, MqttSetupStateUpdate
from app.system.mqtt.integration_state import MqttIntegrationStateStore
from app.system.mqtt.router import build_mqtt_router
from app.system.mqtt.runtime_boundary import InMemoryBrokerRuntimeBoundary
from app.system.mqtt.startup_reconcile import EmbeddedMqttStartupReconciler
from app.system.onboarding import NodeRegistrationRecord, NodeRegistrationsStore


class _FakeSettingsStore:
    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    async def get(self, key: str):
        return self._data.get(key)

    async def set(self, key: str, value):
        self._data[key] = value
        return value


class _FakeMqttManager:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def status(self):
        return {"ok": True, "enabled": True, "connected": True, "last_message_at": None}

    async def restart(self):
        return None

    async def publish_test(self, topic: str | None = None, payload: dict | None = None):
        return {"ok": True, "topic": topic or "hexe/core/mqtt/info", "payload": payload or {}}

    async def publish(self, topic: str, payload: dict, retain: bool = True, qos: int = 1):
        self.published.append((topic, payload))
        return {"ok": True, "topic": topic, "rc": 0}

    def _core_info_payload(self) -> dict:
        return {"source": "synthia-core", "type": "core-mqtt-info"}

    async def principal_connection_states(self):
        return {
            "core.runtime": {
                "connected": True,
                "connected_since": "2026-03-10T00:00:00Z",
                "last_seen": "2026-03-10T00:00:01Z",
                "session_count": 1,
            }
        }

    async def runtime_sessions(self):
        return {
            "ok": True,
            "items": [
                {
                    "client_id": "synthia-core",
                    "principal_id": "core.runtime",
                    "connected": True,
                    "connected_at": "2026-03-10T00:00:00Z",
                    "last_activity": "2026-03-10T00:00:01Z",
                    "session_count": 1,
                }
            ],
            "broker_clients": {"connected": 1, "disconnected": 0},
        }

    async def broker_health_metrics(self):
        return {
            "broker_uptime": "12 seconds",
            "connected_clients": 1,
            "message_rate": 0.5,
            "dropped_messages": 0,
            "retained_messages": 1,
        }

    async def principal_traffic_metrics(self):
        return {
            "user:testuser": {
                "messages_per_second": 3.25,
                "payload_size": 128,
                "topic_count": 2,
            }
        }


class TestMqttRuntimeIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(os.environ, {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False)
        self.env_patch.start()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state_store = MqttIntegrationStateStore(str(root / "state.json"))
        asyncio.run(
            self.state_store.update_setup_state(
                MqttSetupStateUpdate(
                    requires_setup=True,
                    setup_complete=True,
                    setup_status="ready",
                    broker_mode="local",
                    direct_mqtt_supported=False,
                    setup_error=None,
                    authority_mode="embedded_platform",
                    authority_ready=True,
                )
            )
        )
        self.audit_store = MqttAuthorityAuditStore(str(root / "audit.db"))
        self.credential_store = MqttCredentialStore(str(root / "credentials.json"))
        self.node_registrations_store = NodeRegistrationsStore(path=root / "node_registrations.json")
        self.acl_compiler = MqttAclCompiler()
        self.boundary = InMemoryBrokerRuntimeBoundary()
        asyncio.run(self.boundary.ensure_running())
        self.pipeline = MqttApplyPipeline(
            runtime_boundary=self.boundary,
            audit_store=self.audit_store,
            live_dir=str(root / "live"),
        )
        self.manager = _FakeMqttManager()
        self.reconciler = EmbeddedMqttStartupReconciler(
            state_store=self.state_store,
            acl_compiler=self.acl_compiler,
            config_renderer=MqttBrokerConfigRenderer(),
            apply_pipeline=self.pipeline,
            audit_store=self.audit_store,
            credential_store=self.credential_store,
            mqtt_manager=self.manager,
        )
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
                    base_url="http://127.0.0.1:9100",
                )
            },
        )
        self.approval = MqttRegistrationApprovalService(
            registry=self.registry,
            state_store=self.state_store,
            runtime_reconcile_hook=self.reconciler.reconcile_authority,
        )
        self.settings = _FakeSettingsStore()
        self.key_store = ServiceTokenKeyStore(self.settings)
        app = FastAPI()
        app.include_router(
            build_mqtt_router(
                self.manager,
                self.registry,
                self.state_store,
                self.key_store,
                settings_store=self.settings,
                approval_service=self.approval,
                acl_compiler=self.acl_compiler,
                runtime_reconciler=self.reconciler,
                runtime_boundary=self.boundary,
                node_registrations_store=self.node_registrations_store,
            ),
            prefix="/api/system",
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        self.env_patch.stop()

    def test_runtime_reconcile_writes_acl_credentials_and_bootstrap(self) -> None:
        req = MqttRegistrationRequest(
            addon_id="vision",
            access_mode="gateway",
            publish_topics=["hexe/addons/vision/state/#"],
            subscribe_topics=["hexe/addons/vision/command/#"],
            capabilities=MqttCapabilityFlags(),
        )
        approved = asyncio.run(self.approval.approve(req))
        self.assertEqual(approved.status, "approved")
        provision = asyncio.run(self.approval.provision_grant("vision", reason="test"))
        self.assertTrue(provision["ok"])

        result = asyncio.run(self.reconciler.reconcile_startup())
        self.assertTrue(result.ok)
        self.assertEqual(result.runtime_state, "running")
        published_topics = [topic for topic, _ in self.manager.published]
        self.assertIn("hexe/bootstrap/core", published_topics)

        live_dir = Path(self.reconciler.live_dir())
        staged_dir = live_dir.parent / "staged"
        self.assertTrue((staged_dir / "broker.conf").exists())
        acl_text = (live_dir / "acl_compiled.conf").read_text(encoding="utf-8")
        self.assertIn("topic read hexe/bootstrap/core", acl_text)
        self.assertNotIn("topic deny #", acl_text)
        self.assertIn("user hx_vision", acl_text)
        self.assertIn("topic write hexe/addons/vision/state/#", acl_text)

        passwords_text = (live_dir / "passwords.conf").read_text(encoding="utf-8")
        self.assertIn("hx_vision:$7$", passwords_text)
        cred_payload = json.loads(Path(self.credential_store.path).read_text(encoding="utf-8"))
        self.assertIn("addon:vision", cred_payload.get("credentials", {}))
        self.assertTrue(cred_payload["credentials"]["addon:vision"]["password"])
        principals = self.client.get("/api/system/mqtt/principals", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(principals.status_code, 200, principals.text)
        by_id = {item["principal_id"]: item for item in principals.json()["items"]}
        self.assertEqual(by_id["core.scheduler"]["principal_type"], "system")
        self.assertEqual(by_id["core.scheduler"]["managed_by"], "core")
        self.assertEqual(by_id["core.bootstrap"]["principal_type"], "system")
        self.assertEqual(by_id["core.bootstrap"]["managed_by"], "core")
        self.assertIn("runtime_connection", by_id["core.bootstrap"])
        self.assertFalse(bool(by_id["core.bootstrap"]["runtime_connection"]["connected"]))

    def test_mqtt_principals_includes_registered_nodes(self) -> None:
        self.node_registrations_store.upsert(
            NodeRegistrationRecord(
                node_id="node-xyz",
                node_type="ai-node",
                node_name="main-ai-node",
                node_software_version="0.1.0",
                requested_node_type="ai-node",
                capabilities_summary=[],
                trust_status="trusted",
                source_onboarding_session_id="sess-xyz",
                approved_by_user_id="admin",
                approved_at="2026-03-11T00:00:00+00:00",
                created_at="2026-03-11T00:00:00+00:00",
                updated_at="2026-03-11T00:00:00+00:00",
            )
        )
        principals = self.client.get("/api/system/mqtt/principals", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(principals.status_code, 200, principals.text)
        by_id = {item["principal_id"]: item for item in principals.json()["items"]}
        self.assertIn("node:node-xyz", by_id)
        self.assertEqual(by_id["node:node-xyz"]["principal_type"], "synthia_node")
        self.assertEqual(by_id["node:node-xyz"]["status"], "active")
        details = self.client.get("/api/system/mqtt/principals/node:node-xyz", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(details.status_code, 200, details.text)

        sessions = self.client.get("/api/system/runtime/sessions", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(sessions.status_code, 200, sessions.text)
        self.assertTrue(sessions.json()["ok"])
        self.assertEqual(sessions.json()["items"][0]["principal_id"], "core.runtime")

        runtime_health = self.client.get("/api/system/runtime/health", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(runtime_health.status_code, 200, runtime_health.text)
        self.assertEqual(runtime_health.json()["broker_metrics"]["connected_clients"], 1)

    def test_mqtt_principals_populates_runtime_traffic_per_item(self) -> None:
        result = asyncio.run(
            self.approval.create_or_update_generic_user(
                principal_id="user:testuser",
                logical_identity="generic:testuser",
                username="testuser",
                topic_prefix="external/testuser",
                access_mode="private",
                publish_topics=["external/testuser/#"],
                subscribe_topics=["external/testuser/#"],
            )
        )
        self.assertTrue(result["ok"])

        principals = self.client.get("/api/system/mqtt/principals", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(principals.status_code, 200, principals.text)
        by_id = {item["principal_id"]: item for item in principals.json()["items"]}

        self.assertIn("runtime_traffic", by_id["core.bootstrap"])
        self.assertEqual(by_id["core.bootstrap"]["runtime_traffic"]["avg_messages_per_second"], 0.0)
        self.assertIn("runtime_traffic", by_id["user:testuser"])
        self.assertEqual(by_id["user:testuser"]["runtime_traffic"]["avg_messages_per_second"], 3.25)

    def test_setup_apply_local_creates_staged_and_live_runtime_artifacts(self) -> None:
        resp = self.client.post(
            "/api/system/mqtt/setup/apply",
            headers={"X-Admin-Token": "test-token"},
            json={"mode": "local", "host": "127.0.0.1", "port": 1883, "initialize": True},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "local")
        self.assertTrue(payload["runtime"]["healthy"])

        live_dir = Path(self.reconciler.live_dir())
        staged_dir = live_dir.parent / "staged"
        self.assertTrue((staged_dir / "broker.conf").exists())
        self.assertTrue((live_dir / "broker.conf").exists())
        self.assertTrue((live_dir / "acl_compiled.conf").exists())
        self.assertTrue((live_dir / "passwords.conf").exists())

    def test_debug_endpoints_and_topic_validation(self) -> None:
        denied = self.client.get("/api/system/mqtt/debug/acl")
        self.assertEqual(denied.status_code, 401, denied.text)

        asyncio.run(self.reconciler.reconcile_startup())
        acl = self.client.get("/api/system/mqtt/debug/acl", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(acl.status_code, 200, acl.text)
        self.assertIn("acl_text", acl.json())

        config = self.client.get("/api/system/mqtt/debug/config", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(config.status_code, 200, config.text)
        self.assertIn("broker.conf", config.json()["files"])

        authority = self.client.get("/api/system/mqtt/debug/authority", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(authority.status_code, 200, authority.text)
        self.assertIn("principals", authority.json())

        validate = self.client.post(
            "/api/system/mqtt/debug/topic-validate",
            headers={"X-Admin-Token": "test-token"},
            json={
                "addon_id": "vision",
                "publish_topics": ["hexe/addons/other/state"],
                "subscribe_topics": ["hexe/bootstrap/core"],
            },
        )
        self.assertEqual(validate.status_code, 200, validate.text)
        self.assertFalse(validate.json()["ok"])
        self.assertGreater(len(validate.json()["errors"]), 0)


if __name__ == "__main__":
    unittest.main()

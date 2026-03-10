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
        return {"ok": True, "topic": topic or "synthia/core/mqtt/info", "payload": payload or {}}

    async def publish(self, topic: str, payload: dict, retain: bool = True, qos: int = 1):
        self.published.append((topic, payload))
        return {"ok": True, "topic": topic, "rc": 0}

    def _core_info_payload(self) -> dict:
        return {"source": "synthia-core", "type": "core-mqtt-info"}


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
            publish_topics=["synthia/addons/vision/state/#"],
            subscribe_topics=["synthia/addons/vision/command/#"],
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
        self.assertIn("synthia/bootstrap/core", published_topics)

        live_dir = Path(self.reconciler.live_dir())
        staged_dir = live_dir.parent / "staged"
        self.assertTrue((staged_dir / "broker.conf").exists())
        acl_text = (live_dir / "acl_compiled.conf").read_text(encoding="utf-8")
        self.assertIn("anonymous allow subscribe synthia/bootstrap/core", acl_text)
        self.assertIn("anonymous deny publish #", acl_text)
        self.assertIn("anonymous deny subscribe #", acl_text)
        self.assertIn("addon:vision allow publish synthia/addons/vision/state/#", acl_text)

        passwords_text = (live_dir / "passwords.conf").read_text(encoding="utf-8")
        self.assertIn("sx_vision:$7$", passwords_text)
        cred_payload = json.loads(Path(self.credential_store.path).read_text(encoding="utf-8"))
        self.assertIn("addon:vision", cred_payload.get("credentials", {}))
        self.assertTrue(cred_payload["credentials"]["addon:vision"]["password"])

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
                "publish_topics": ["synthia/addons/other/state"],
                "subscribe_topics": ["synthia/bootstrap/core"],
            },
        )
        self.assertEqual(validate.status_code, 200, validate.text)
        self.assertFalse(validate.json()["ok"])
        self.assertGreater(len(validate.json()["errors"]), 0)


if __name__ == "__main__":
    unittest.main()

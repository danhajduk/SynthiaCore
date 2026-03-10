import asyncio
import tempfile
import unittest
from pathlib import Path

from app.system.mqtt.acl_compiler import MqttAclCompiler
from app.system.mqtt.apply_pipeline import MqttApplyPipeline
from app.system.mqtt.authority_audit import MqttAuthorityAuditStore
from app.system.mqtt.config_renderer import MqttBrokerConfigRenderer
from app.system.mqtt.credential_store import MqttCredentialStore
from app.system.mqtt.integration_models import MqttPrincipal
from app.system.mqtt.integration_state import MqttIntegrationStateStore
from app.system.mqtt.runtime_boundary import InMemoryBrokerRuntimeBoundary
from app.system.mqtt.startup_reconcile import EmbeddedMqttStartupReconciler


class _FakeMqttManager:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []
        self.fail_publish = False

    async def publish(self, topic: str, payload: dict, retain: bool = True, qos: int = 1):
        if self.fail_publish:
            return {"ok": False, "topic": topic, "error": "mqtt_not_initialized"}
        self.published.append((topic, payload))
        return {"ok": True, "topic": topic, "rc": 0}

    def _core_info_payload(self) -> dict:
        return {"source": "synthia-core", "type": "core-mqtt-info"}


class TestMqttStartupReconcile(unittest.TestCase):
    def test_reconcile_success_marks_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_store = MqttIntegrationStateStore(str(Path(tmp) / "state.json"))
            audit = MqttAuthorityAuditStore(str(Path(tmp) / "audit.db"))
            boundary = InMemoryBrokerRuntimeBoundary()
            asyncio.run(boundary.ensure_running())
            cred_store = MqttCredentialStore(str(Path(tmp) / "credentials.json"))
            asyncio.run(
                state_store.upsert_principal(
                    MqttPrincipal(
                        principal_id="addon:vision",
                        principal_type="synthia_addon",
                        status="active",
                        logical_identity="vision",
                        linked_addon_id="vision",
                        username="vision-user",
                    )
                )
            )
            pipeline = MqttApplyPipeline(
                runtime_boundary=boundary,
                audit_store=audit,
                live_dir=str(Path(tmp) / "live"),
            )
            fake_manager = _FakeMqttManager()
            reconciler = EmbeddedMqttStartupReconciler(
                state_store=state_store,
                acl_compiler=MqttAclCompiler(),
                config_renderer=MqttBrokerConfigRenderer(),
                apply_pipeline=pipeline,
                audit_store=audit,
                credential_store=cred_store,
                mqtt_manager=fake_manager,
            )
            result = asyncio.run(reconciler.reconcile_startup())
            self.assertTrue(result.ok)
            self.assertEqual(result.setup_status, "ready")
            self.assertGreaterEqual(len(fake_manager.published), 2)
            password_text = (Path(tmp) / "live" / "passwords.conf").read_text(encoding="utf-8")
            self.assertIn("vision-user:$7$", password_text)
            state = asyncio.run(state_store.get_state())
            for principal_id in [
                "core.scheduler",
                "core.supervisor",
                "core.telemetry",
                "core.runtime",
                "core.bootstrap",
            ]:
                self.assertIn(principal_id, state.principals)
                self.assertEqual(state.principals[principal_id].principal_type, "system")
                self.assertEqual(state.principals[principal_id].managed_by, "core")

    def test_bootstrap_publish_retries_after_runtime_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_store = MqttIntegrationStateStore(str(Path(tmp) / "state.json"))
            audit = MqttAuthorityAuditStore(str(Path(tmp) / "audit.db"))
            boundary = InMemoryBrokerRuntimeBoundary()
            asyncio.run(boundary.ensure_running())
            pipeline = MqttApplyPipeline(
                runtime_boundary=boundary,
                audit_store=audit,
                live_dir=str(Path(tmp) / "live"),
            )
            fake_manager = _FakeMqttManager()
            fake_manager.fail_publish = True
            reconciler = EmbeddedMqttStartupReconciler(
                state_store=state_store,
                acl_compiler=MqttAclCompiler(),
                config_renderer=MqttBrokerConfigRenderer(),
                apply_pipeline=pipeline,
                audit_store=audit,
                credential_store=MqttCredentialStore(str(Path(tmp) / "credentials.json")),
                mqtt_manager=fake_manager,
            )
            result = asyncio.run(reconciler.reconcile_startup())
            self.assertTrue(result.ok)
            self.assertFalse(reconciler.bootstrap_status()["published"])
            fake_manager.fail_publish = False
            published = asyncio.run(reconciler.ensure_bootstrap_published())
            self.assertTrue(published)
            self.assertTrue(reconciler.bootstrap_status()["published"])

    def test_bootstrap_publish_skips_when_runtime_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_store = MqttIntegrationStateStore(str(Path(tmp) / "state.json"))
            audit = MqttAuthorityAuditStore(str(Path(tmp) / "audit.db"))
            boundary = InMemoryBrokerRuntimeBoundary()
            pipeline = MqttApplyPipeline(
                runtime_boundary=boundary,
                audit_store=audit,
                live_dir=str(Path(tmp) / "live"),
            )
            fake_manager = _FakeMqttManager()
            reconciler = EmbeddedMqttStartupReconciler(
                state_store=state_store,
                acl_compiler=MqttAclCompiler(),
                config_renderer=MqttBrokerConfigRenderer(),
                apply_pipeline=pipeline,
                audit_store=audit,
                credential_store=MqttCredentialStore(str(Path(tmp) / "credentials.json")),
                mqtt_manager=fake_manager,
            )
            published = asyncio.run(reconciler.ensure_bootstrap_published(force=True))
            self.assertFalse(published)
            self.assertEqual(len(fake_manager.published), 0)


if __name__ == "__main__":
    unittest.main()

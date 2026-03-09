import asyncio
import tempfile
import unittest
from pathlib import Path

from app.system.mqtt.acl_compiler import MqttAclCompiler
from app.system.mqtt.apply_pipeline import MqttApplyPipeline
from app.system.mqtt.authority_audit import MqttAuthorityAuditStore
from app.system.mqtt.config_renderer import MqttBrokerConfigRenderer
from app.system.mqtt.integration_state import MqttIntegrationStateStore
from app.system.mqtt.runtime_boundary import InMemoryBrokerRuntimeBoundary
from app.system.mqtt.startup_reconcile import EmbeddedMqttStartupReconciler


class _FakeMqttManager:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def publish(self, topic: str, payload: dict, retain: bool = True, qos: int = 1):
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
                mqtt_manager=fake_manager,
            )
            result = asyncio.run(reconciler.reconcile_startup())
            self.assertTrue(result.ok)
            self.assertEqual(result.setup_status, "ready")
            self.assertGreaterEqual(len(fake_manager.published), 2)


if __name__ == "__main__":
    unittest.main()

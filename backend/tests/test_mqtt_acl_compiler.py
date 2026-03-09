import unittest

from app.system.mqtt.acl_compiler import MqttAclCompiler
from app.system.mqtt.integration_models import MqttAddonGrant, MqttIntegrationState, MqttPrincipal


class TestMqttAclCompiler(unittest.TestCase):
    def test_compiles_anonymous_and_generic_denials(self) -> None:
        compiler = MqttAclCompiler()
        result = compiler.compile(MqttIntegrationState())
        acl = result.acl_text
        self.assertIn("anonymous allow subscribe synthia/bootstrap/core", acl)
        self.assertIn("generic_user:* deny subscribe synthia/core/#", acl)
        self.assertGreaterEqual(len(result.effective_access), 1)

    def test_compiles_active_synthia_principal_rules(self) -> None:
        state = MqttIntegrationState(
            principals={
                "addon:vision": MqttPrincipal(
                    principal_id="addon:vision",
                    principal_type="synthia_addon",
                    status="active",
                    logical_identity="vision",
                    linked_addon_id="vision",
                )
            },
            active_grants={
                "vision": MqttAddonGrant(
                    addon_id="vision",
                    status="active",
                    publish_topics=["synthia/addons/vision/event/#"],
                    subscribe_topics=["synthia/system/health"],
                )
            },
        )
        compiler = MqttAclCompiler()
        result = compiler.compile(state)
        acl = result.acl_text
        self.assertIn("addon:vision allow publish synthia/addons/vision/event/#", acl)
        self.assertIn("addon:vision allow subscribe synthia/system/health", acl)


if __name__ == "__main__":
    unittest.main()

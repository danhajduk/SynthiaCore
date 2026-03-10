import unittest

from app.system.mqtt.acl_compiler import MqttAclCompiler
from app.system.mqtt.integration_models import MqttAddonGrant, MqttIntegrationState, MqttPrincipal


class TestMqttAclCompiler(unittest.TestCase):
    def test_compiles_anonymous_and_generic_denials(self) -> None:
        compiler = MqttAclCompiler()
        result = compiler.compile(MqttIntegrationState())
        acl = result.acl_text
        self.assertIn("topic read synthia/bootstrap/core", acl)
        self.assertIn("topic deny #", acl)
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
                    username="sx_vision",
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
        self.assertIn("user sx_vision", acl)
        self.assertIn("topic write synthia/addons/vision/event/#", acl)
        self.assertIn("topic read synthia/system/health", acl)

    def test_generic_user_reserved_denies_include_future_federation_families(self) -> None:
        state = MqttIntegrationState(
            principals={
                "user:guest": MqttPrincipal(
                    principal_id="user:guest",
                    principal_type="generic_user",
                    status="active",
                    logical_identity="guest",
                    username="guest",
                    access_mode="custom",
                    allowed_topics=["external/guest/#"],
                    publish_topics=["external/guest/#"],
                    subscribe_topics=["external/guest/#"],
                )
            }
        )
        compiler = MqttAclCompiler()
        acl = compiler.compile(state).acl_text
        self.assertIn("topic deny synthia/runtime/#", acl)
        self.assertIn("topic deny synthia/remote/#", acl)
        self.assertIn("topic deny synthia/bridges/#", acl)
        self.assertIn("topic deny synthia/import/#", acl)


if __name__ == "__main__":
    unittest.main()

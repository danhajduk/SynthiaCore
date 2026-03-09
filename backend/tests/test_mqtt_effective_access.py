import unittest

from app.system.mqtt.effective_access import MqttEffectiveAccessCompiler
from app.system.mqtt.integration_models import MqttAddonGrant, MqttIntegrationState, MqttPrincipal


class TestMqttEffectiveAccess(unittest.TestCase):
    def test_compiles_effective_access_before_acl_rendering(self) -> None:
        state = MqttIntegrationState(
            principals={
                "addon:vision": MqttPrincipal(
                    principal_id="addon:vision",
                    principal_type="synthia_addon",
                    status="active",
                    logical_identity="vision",
                    linked_addon_id="vision",
                ),
                "user:guest1": MqttPrincipal(
                    principal_id="user:guest1",
                    principal_type="generic_user",
                    status="active",
                    logical_identity="guest1",
                    publish_topics=["devices/guest1/state", "synthia/core/should-deny"],
                    subscribe_topics=["devices/guest1/cmd", "synthia/system/should-deny"],
                ),
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
        compiled = MqttEffectiveAccessCompiler().compile(state)
        by_id = {item.principal_id: item for item in compiled}
        self.assertIn("anonymous", by_id)
        self.assertTrue(by_id["anonymous"].anonymous_bootstrap_only)
        self.assertEqual(by_id["anonymous"].subscribe_scopes, ["synthia/bootstrap/core"])

        self.assertIn("addon:vision", by_id)
        self.assertIn("synthia/addons/vision/event/#", by_id["addon:vision"].publish_scopes)

        self.assertIn("user:guest1", by_id)
        self.assertTrue(by_id["user:guest1"].generic_non_reserved_only)
        self.assertNotIn("synthia/core/should-deny", by_id["user:guest1"].publish_scopes)
        self.assertIn("synthia/core/#", by_id["user:guest1"].reserved_prefix_denies)


if __name__ == "__main__":
    unittest.main()

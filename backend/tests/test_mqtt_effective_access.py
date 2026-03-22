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
                    publish_topics=["devices/guest1/state", "hexe/core/should-deny"],
                    subscribe_topics=["devices/guest1/cmd", "hexe/system/should-deny"],
                ),
                "core.runtime": MqttPrincipal(
                    principal_id="core.runtime",
                    principal_type="system",
                    status="active",
                    logical_identity="core.runtime",
                    publish_topics=["hexe/core/mqtt/info"],
                    subscribe_topics=["#", "$SYS/#"],
                ),
            },
            active_grants={
                "vision": MqttAddonGrant(
                    addon_id="vision",
                    status="active",
                    publish_topics=["hexe/addons/vision/event/#"],
                    subscribe_topics=["hexe/system/health"],
                )
            },
        )
        compiled = MqttEffectiveAccessCompiler().compile(state)
        by_id = {item.principal_id: item for item in compiled}
        self.assertIn("anonymous", by_id)
        self.assertTrue(by_id["anonymous"].anonymous_bootstrap_only)
        self.assertEqual(by_id["anonymous"].subscribe_scopes, ["hexe/bootstrap/core"])

        self.assertIn("addon:vision", by_id)
        self.assertIn("hexe/addons/vision/event/#", by_id["addon:vision"].publish_scopes)

        self.assertIn("user:guest1", by_id)
        self.assertFalse(by_id["user:guest1"].generic_non_reserved_only)
        self.assertNotIn("hexe/core/should-deny", by_id["user:guest1"].publish_scopes)
        self.assertIn("hexe/core/#", by_id["user:guest1"].reserved_prefix_denies)

        self.assertIn("core.runtime", by_id)
        self.assertIn("#", by_id["core.runtime"].subscribe_scopes)
        self.assertIn("$SYS/#", by_id["core.runtime"].subscribe_scopes)
        self.assertIn("hexe/core/mqtt/info", by_id["core.runtime"].publish_scopes)

    def test_compiles_direct_node_topics_without_addon_grant(self) -> None:
        state = MqttIntegrationState(
            principals={
                "node:node-123": MqttPrincipal(
                    principal_id="node:node-123",
                    principal_type="synthia_node",
                    status="active",
                    logical_identity="node-123",
                    linked_node_id="node-123",
                    username="hn_node-123",
                    publish_topics=["hexe/nodes/node-123/#"],
                    subscribe_topics=["hexe/nodes/node-123/#"],
                )
            }
        )
        compiled = MqttEffectiveAccessCompiler().compile(state)
        by_id = {item.principal_id: item for item in compiled}
        self.assertIn("node:node-123", by_id)
        self.assertEqual(by_id["node:node-123"].publish_scopes, ["hexe/nodes/node-123/#"])
        self.assertEqual(by_id["node:node-123"].subscribe_scopes, ["hexe/nodes/node-123/#"])


if __name__ == "__main__":
    unittest.main()

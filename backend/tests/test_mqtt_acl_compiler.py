import unittest

from app.system.mqtt.acl_compiler import CompiledAclRule, MqttAclCompiler
from app.system.mqtt.integration_models import MqttAddonGrant, MqttIntegrationState, MqttPrincipal


class TestMqttAclCompiler(unittest.TestCase):
    def test_compiles_anonymous_and_generic_denials(self) -> None:
        compiler = MqttAclCompiler()
        result = compiler.compile(MqttIntegrationState())
        acl = result.acl_text
        self.assertIn("topic read synthia/bootstrap/core", acl)
        self.assertNotIn("topic deny #", acl)
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

    def test_compiles_synthia_principal_without_username_using_credential_style_name(self) -> None:
        state = MqttIntegrationState(
            principals={
                "addon:mqtt": MqttPrincipal(
                    principal_id="addon:mqtt",
                    principal_type="synthia_addon",
                    status="active",
                    logical_identity="mqtt",
                    linked_addon_id="mqtt",
                    username=None,
                )
            },
            active_grants={
                "mqtt": MqttAddonGrant(
                    addon_id="mqtt",
                    status="active",
                    publish_topics=["synthia/addons/mqtt/event/#"],
                    subscribe_topics=["synthia/addons/mqtt/command/#"],
                )
            },
        )
        acl = MqttAclCompiler().compile(state).acl_text
        self.assertIn("user sx_mqtt", acl)
        self.assertNotIn("user addon_mqtt", acl)

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
        self.assertIn("topic deny synthia/#", acl)
        self.assertIn("topic deny $SYS/#", acl)
        self.assertEqual(acl.count("topic deny synthia/#"), 1)

    def test_collapses_redundant_deny_children_under_parent(self) -> None:
        rules = [
            ("anonymous", "publish", "synthia/#", "deny"),
            ("anonymous", "publish", "synthia/runtime/#", "deny"),
            ("anonymous", "publish", "synthia/bootstrap/#", "deny"),
        ]
        compiler = MqttAclCompiler()
        normalized = compiler._normalize_rules([CompiledAclRule(*rule) for rule in rules])  # type: ignore[attr-defined]
        topics = [rule.topic for rule in normalized if rule.effect == "deny" and rule.action == "publish"]
        self.assertIn("synthia/#", topics)
        self.assertNotIn("synthia/runtime/#", topics)
        self.assertNotIn("synthia/bootstrap/#", topics)

    def test_merges_publish_and_subscribe_allows_into_readwrite(self) -> None:
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
        acl = MqttAclCompiler().compile(state).acl_text
        self.assertIn("topic readwrite external/guest/#", acl)

    def test_non_reserved_mode_keeps_deny_strategy_and_admin_mode_is_full_access(self) -> None:
        state = MqttIntegrationState(
            principals={
                "user:nonres": MqttPrincipal(
                    principal_id="user:nonres",
                    principal_type="generic_user",
                    status="active",
                    logical_identity="nonres",
                    username="nonres",
                    access_mode="non_reserved",
                    publish_topics=["#"],
                    subscribe_topics=["#"],
                ),
                "user:admin": MqttPrincipal(
                    principal_id="user:admin",
                    principal_type="generic_user",
                    status="active",
                    logical_identity="admin",
                    username="admin",
                    access_mode="admin",
                    publish_topics=["#"],
                    subscribe_topics=["#"],
                ),
            }
        )
        compiler = MqttAclCompiler()
        acl = compiler.compile(state).acl_text
        self.assertIn("user nonres", acl)
        self.assertIn("topic readwrite #", acl)
        self.assertIn("topic deny synthia/#", acl)
        self.assertIn("topic deny $SYS/#", acl)
        self.assertIn("user admin", acl)
        # Admin mode keeps broad allow without reserved deny overlays.
        admin_section = acl.split("user admin", 1)[1].split("\n\nuser ", 1)[0]
        self.assertIn("topic readwrite #", admin_section)
        self.assertNotIn("topic deny synthia/#", admin_section)

    def test_normalized_effective_access_exposes_permission_summary(self) -> None:
        state = MqttIntegrationState(
            principals={
                "user:guest": MqttPrincipal(
                    principal_id="user:guest",
                    principal_type="generic_user",
                    status="active",
                    logical_identity="guest",
                    username="guest",
                    access_mode="non_reserved",
                    publish_topics=["#"],
                    subscribe_topics=["#"],
                )
            }
        )
        normalized = MqttAclCompiler().inspect_normalized_effective_access(state, "user:guest")
        self.assertIsNotNone(normalized)
        item = normalized
        assert item is not None
        self.assertEqual(item.access_mode, "non_reserved")
        self.assertTrue(item.all_non_reserved)
        self.assertIn("#", item.read_rules)
        self.assertIn("#", item.write_rules)
        self.assertIn("synthia/#", item.deny_rules)


if __name__ == "__main__":
    unittest.main()

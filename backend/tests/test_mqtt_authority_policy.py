import unittest

from app.system.mqtt.authority_policy import (
    DEFAULT_BOOTSTRAP_TOPIC,
    is_reserved_platform_topic,
    validate_authority_topic_access,
)


class TestMqttAuthorityPolicy(unittest.TestCase):
    def test_reserved_platform_topic_detection(self) -> None:
        self.assertTrue(is_reserved_platform_topic("synthia/system/events"))
        self.assertTrue(is_reserved_platform_topic("synthia/core/mqtt/info"))
        self.assertFalse(is_reserved_platform_topic("synthia/addons/vision/state/main"))

    def test_generic_user_reserved_access_denied(self) -> None:
        errors = validate_authority_topic_access(
            principal_type="generic_user",
            publish_topics=["synthia/core/mqtt/info", "devices/home/state"],
            subscribe_topics=["synthia/system/health", "devices/home/command"],
        )
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("generic_user publish topic 'synthia/core/mqtt/info'" in item for item in errors))
        self.assertTrue(any("generic_user subscribe topic 'synthia/system/health'" in item for item in errors))

    def test_anonymous_bootstrap_only(self) -> None:
        allowed = validate_authority_topic_access(
            principal_type="anonymous",
            publish_topics=[],
            subscribe_topics=[DEFAULT_BOOTSTRAP_TOPIC],
        )
        self.assertEqual(allowed, [])

        denied = validate_authority_topic_access(
            principal_type="anonymous",
            publish_topics=["synthia/bootstrap/core"],
            subscribe_topics=["synthia/system/#"],
        )
        self.assertEqual(len(denied), 2)
        self.assertTrue(any("anonymous publish topic" in item for item in denied))
        self.assertTrue(any("only 'synthia/bootstrap/core' is permitted" in item for item in denied))

    def test_synthia_principal_reserved_requires_explicit_approval(self) -> None:
        denied = validate_authority_topic_access(
            principal_type="synthia_addon",
            publish_topics=["synthia/system/events"],
            subscribe_topics=["synthia/core/mqtt/info"],
            approved_reserved_topics=[],
        )
        self.assertEqual(len(denied), 2)

        allowed = validate_authority_topic_access(
            principal_type="synthia_addon",
            publish_topics=["synthia/system/events"],
            subscribe_topics=["synthia/core/mqtt/info"],
            approved_reserved_topics=["synthia/system/events", "synthia/core/mqtt/info"],
        )
        self.assertEqual(allowed, [])


if __name__ == "__main__":
    unittest.main()

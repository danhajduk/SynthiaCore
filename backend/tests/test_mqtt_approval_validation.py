import asyncio
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.system.mqtt import (
    MqttRegistrationApprovalService,
    MqttRegistrationRequest,
    MqttSetupStateUpdate,
)
from app.system.mqtt.integration_state import MqttIntegrationStateStore


class _RegisteredAddon:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


class _FakeRegistry:
    def __init__(self) -> None:
        self.registered = {"mqtt": _RegisteredAddon("http://mqtt-addon.local:9100")}

    def has_addon(self, addon_id: str) -> bool:
        return addon_id == "vision"

    def is_enabled(self, addon_id: str) -> bool:
        return addon_id == "vision"


class TestMqttApprovalValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.state_store = MqttIntegrationStateStore(str(Path(self.tmpdir.name) / "mqtt_state.json"))
        self.registry = _FakeRegistry()
        self.service = MqttRegistrationApprovalService(registry=self.registry, state_store=self.state_store)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_valid_and_invalid_topic_scope_validation(self) -> None:
        approved = asyncio.run(
            self.service.approve(
                MqttRegistrationRequest(
                    addon_id="vision",
                    access_mode="gateway",
                    publish_topics=["synthia/addons/vision/state/main"],
                    subscribe_topics=["synthia/system/#", "synthia/addons/vision/command/#"],
                )
            )
        )
        self.assertEqual(approved.status, "approved")

        rejected = asyncio.run(
            self.service.approve(
                MqttRegistrationRequest(
                    addon_id="vision",
                    access_mode="gateway",
                    publish_topics=["synthia/addons/other/state/main"],
                    subscribe_topics=[],
                )
            )
        )
        self.assertEqual(rejected.status, "rejected")
        self.assertIn("topic_scope_invalid", str(rejected.reason))

    def test_reserved_namespace_rejection(self) -> None:
        rejected = asyncio.run(
            self.service.approve(
                MqttRegistrationRequest(
                    addon_id="vision",
                    access_mode="gateway",
                    publish_topics=["synthia/core/config/update"],
                    subscribe_topics=[],
                )
            )
        )
        self.assertEqual(rejected.status, "rejected")
        self.assertIn("requires explicit reserved approval", str(rejected.reason))

    def test_access_mode_validation_rejects_invalid_value(self) -> None:
        with self.assertRaises(ValidationError):
            MqttRegistrationRequest(
                addon_id="vision",
                access_mode="invalid",  # type: ignore[arg-type]
                publish_topics=["synthia/addons/vision/state/main"],
                subscribe_topics=[],
            )

    def test_revoke_and_reprovision_lifecycle(self) -> None:
        asyncio.run(
            self.service.update_setup_state(
                MqttSetupStateUpdate(
                    requires_setup=True,
                    setup_complete=True,
                    setup_status="ready",
                    broker_mode="external",
                    direct_mqtt_supported=True,
                    authority_ready=True,
                )
            )
        )

        asyncio.run(
            self.service.approve(
                MqttRegistrationRequest(
                    addon_id="vision",
                    access_mode="both",
                    publish_topics=["synthia/addons/vision/event/#"],
                    subscribe_topics=["synthia/system/#"],
                )
            )
        )
        provisioned = asyncio.run(self.service.provision_grant("vision", reason="test"))
        self.assertTrue(provisioned["ok"])
        self.assertEqual(provisioned["status"], "active")

        asyncio.run(
            self.service.approve(
                MqttRegistrationRequest(
                    addon_id="vision",
                    access_mode="both",
                    publish_topics=["synthia/addons/vision/event/#", "synthia/addons/vision/state/#"],
                    subscribe_topics=["synthia/system/#"],
                )
            )
        )
        reprovisioned = asyncio.run(self.service.provision_grant("vision", reason="grant_scope_changed"))
        self.assertTrue(reprovisioned["ok"])
        self.assertEqual(reprovisioned["status"], "active")

        revoked = asyncio.run(self.service.revoke_or_mark("vision", reason="test_revoke"))
        self.assertTrue(revoked["ok"])
        self.assertEqual(revoked["status"], "revoked")

    def test_ha_discovery_mode_validation(self) -> None:
        valid = MqttRegistrationRequest(
            addon_id="vision",
            access_mode="gateway",
            publish_topics=["synthia/addons/vision/state/main"],
            subscribe_topics=[],
            capabilities={"ha_discovery": "gateway_managed"},
        )
        self.assertEqual(valid.capabilities.ha_discovery, "gateway_managed")

        with self.assertRaises(ValidationError):
            MqttRegistrationRequest(
                addon_id="vision",
                access_mode="gateway",
                publish_topics=["synthia/addons/vision/state/main"],
                subscribe_topics=[],
                capabilities={"ha_discovery": "unsupported_mode"},
            )

    def test_reconcile_bootstraps_grant_for_enabled_addon(self) -> None:
        asyncio.run(
            self.service.update_setup_state(
                MqttSetupStateUpdate(
                    requires_setup=True,
                    setup_complete=True,
                    setup_status="ready",
                    broker_mode="embedded",
                    direct_mqtt_supported=True,
                    authority_ready=True,
                )
            )
        )
        result = asyncio.run(self.service.reconcile("vision"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "active")


if __name__ == "__main__":
    unittest.main()

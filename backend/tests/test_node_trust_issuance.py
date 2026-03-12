import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.system.onboarding import NodeOnboardingSessionsStore, NodeTrustIssuanceService, NodeTrustStore


class TestNodeTrustIssuanceService(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        base = Path(self.tmpdir.name)
        self.sessions = NodeOnboardingSessionsStore(path=base / "sessions.json")
        self.trust_store = NodeTrustStore(path=base / "trust.json")
        self.service = NodeTrustIssuanceService(self.trust_store)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_rejects_non_approved_session(self) -> None:
        session = self.sessions.start_session(
            node_nonce="nonce-a",
            requested_node_name="node-a",
            requested_node_type="ai-node",
            requested_node_software_version="0.1.0",
        )
        with self.assertRaisesRegex(ValueError, "session_not_approved"):
            self.service.issue_for_approved_session(session)

    def test_issues_and_reuses_same_payload_for_session(self) -> None:
        session = self.sessions.start_session(
            node_nonce="nonce-b",
            requested_node_name="node-b",
            requested_node_type="ai-node",
            requested_node_software_version="0.2.0",
        )
        approved = self.sessions.approve_session(
            session.session_id,
            approved_by_user_id="admin_session",
            linked_node_id="node-fixed-1",
        )

        first = self.service.issue_for_approved_session(approved)
        second = self.service.issue_for_approved_session(approved)

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(first["activation"]["node_id"], "node-fixed-1")
        self.assertEqual(first["activation"]["node_type"], "ai-node")
        self.assertEqual(first["activation"]["activation_profile"]["node_type"], "ai-node")
        self.assertEqual(first["activation"]["node_trust_token"], second["activation"]["node_trust_token"])
        self.assertEqual(first["activation"]["operational_mqtt_token"], second["activation"]["operational_mqtt_token"])
        self.assertEqual(first["activation"]["source_session_id"], approved.session_id)
        self.assertNotIn(first["activation"]["operational_mqtt_host"], {"127.0.0.1", "localhost", "0.0.0.0", "::1"})

    def test_persists_trust_record(self) -> None:
        session = self.sessions.start_session(
            node_nonce="nonce-c",
            requested_node_name="node-c",
            requested_node_type="ai-node",
            requested_node_software_version="0.3.0",
        )
        approved = self.sessions.approve_session(
            session.session_id,
            approved_by_user_id="admin_session",
            linked_node_id="node-fixed-2",
        )
        issued = self.service.issue_for_approved_session(approved)["activation"]

        reloaded_store = NodeTrustStore(path=Path(self.tmpdir.name) / "trust.json")
        reloaded = reloaded_store.get_by_session(approved.session_id)
        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        self.assertEqual(reloaded.node_id, "node-fixed-2")
        self.assertEqual(reloaded.node_trust_token, issued["node_trust_token"])

    def test_sensor_node_type_activation_profile(self) -> None:
        session = self.sessions.start_session(
            node_nonce="nonce-d",
            requested_node_name="sensor-d",
            requested_node_type="sensor-node",
            requested_node_software_version="1.4.0",
        )
        approved = self.sessions.approve_session(
            session.session_id,
            approved_by_user_id="admin_session",
            linked_node_id="sensor-fixed-1",
        )
        issued = self.service.issue_for_approved_session(approved)["activation"]
        self.assertEqual(issued["node_type"], "sensor-node")
        self.assertEqual(issued["activation_profile"]["node_type"], "sensor-node")

    def test_loopback_env_value_falls_back_to_advertise_host(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SYNTHIA_NODE_OPERATIONAL_MQTT_HOST": "127.0.0.1",
                "SYNTHIA_BOOTSTRAP_ADVERTISE_HOST": "10.0.0.100",
            },
            clear=False,
        ):
            service = NodeTrustIssuanceService(self.trust_store)
        session = self.sessions.start_session(
            node_nonce="nonce-e",
            requested_node_name="node-e",
            requested_node_type="ai-node",
            requested_node_software_version="0.1.0",
        )
        approved = self.sessions.approve_session(
            session.session_id,
            approved_by_user_id="admin_session",
            linked_node_id="node-fixed-3",
        )
        issued = service.issue_for_approved_session(approved)["activation"]
        self.assertEqual(issued["operational_mqtt_host"], "10.0.0.100")

    def test_service_startup_migrates_existing_loopback_hosts(self) -> None:
        session = self.sessions.start_session(
            node_nonce="nonce-f",
            requested_node_name="node-f",
            requested_node_type="ai-node",
            requested_node_software_version="0.1.0",
        )
        approved = self.sessions.approve_session(
            session.session_id,
            approved_by_user_id="admin_session",
            linked_node_id="node-fixed-4",
        )
        issued = self.service.issue_for_approved_session(approved)["activation"]
        self.assertTrue(str(issued["operational_mqtt_host"]).strip())

        existing = self.trust_store.get_by_node("node-fixed-4")
        assert existing is not None
        existing.operational_mqtt_host = "127.0.0.1"
        self.trust_store.upsert(existing)

        with patch.dict("os.environ", {"SYNTHIA_BOOTSTRAP_ADVERTISE_HOST": "10.0.0.123"}, clear=False):
            upgraded_service = NodeTrustIssuanceService(self.trust_store)
        upgraded = self.trust_store.get_by_node("node-fixed-4")
        self.assertIsNotNone(upgraded)
        assert upgraded is not None
        self.assertEqual(upgraded.operational_mqtt_host, "10.0.0.123")

        replay = upgraded_service.issue_for_approved_session(approved)["activation"]
        self.assertEqual(replay["operational_mqtt_host"], "10.0.0.123")


if __name__ == "__main__":
    unittest.main()

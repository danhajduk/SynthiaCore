import tempfile
import unittest
from pathlib import Path

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
        self.assertEqual(first["activation"]["node_trust_token"], second["activation"]["node_trust_token"])
        self.assertEqual(first["activation"]["operational_mqtt_token"], second["activation"]["operational_mqtt_token"])
        self.assertEqual(first["activation"]["source_session_id"], approved.session_id)

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


if __name__ == "__main__":
    unittest.main()

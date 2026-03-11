import tempfile
import unittest
from pathlib import Path

from app.system.onboarding.registrations import NodeRegistrationRecord, NodeRegistrationsStore
from app.system.onboarding.sessions import NodeOnboardingSession


class TestNodeRegistrationsStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "node_registrations.json"
        self.store = NodeRegistrationsStore(path=self.path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_upsert_and_reload_record(self) -> None:
        record = NodeRegistrationRecord(
            node_id="node-001",
            node_type="ai-node",
            node_name="office-node",
            node_software_version="1.2.3",
            capabilities_summary=["vision", "alerts"],
            trust_status="approved",
            source_onboarding_session_id="sess-001",
            approved_by_user_id="admin:alice",
            approved_at="2026-03-11T00:00:00+00:00",
            created_at="2026-03-11T00:00:00+00:00",
            updated_at="2026-03-11T00:00:00+00:00",
        )
        self.store.upsert(record)

        reloaded = NodeRegistrationsStore(path=self.path)
        by_id = reloaded.get("node-001")
        self.assertIsNotNone(by_id)
        assert by_id is not None
        self.assertEqual(by_id.node_name, "office-node")
        self.assertEqual(by_id.node_type, "ai-node")
        self.assertEqual(by_id.node_software_version, "1.2.3")
        self.assertEqual(by_id.trust_status, "approved")
        by_session = reloaded.get_by_session("sess-001")
        self.assertIsNotNone(by_session)
        assert by_session is not None
        self.assertEqual(by_session.node_id, "node-001")

    def test_upsert_from_approved_session_binds_session_mapping(self) -> None:
        session = NodeOnboardingSession(
            session_id="sess-448",
            session_state="approved",
            node_nonce="nonce-1",
            requested_node_name="kitchen-node",
            requested_node_type="ai-node",
            requested_node_software_version="2.0.0",
            requested_hostname=None,
            requested_from_ip=None,
            request_metadata={},
            created_at="2026-03-11T00:00:00+00:00",
            expires_at="2026-03-11T00:15:00+00:00",
            approved_at="2026-03-11T00:01:00+00:00",
            rejected_at=None,
            approved_by_user_id="admin:bob",
            rejection_reason=None,
            linked_node_id="node-448",
            final_payload_consumed_at=None,
            state_history=[],
        )

        created = self.store.upsert_from_approved_session(session)
        self.assertEqual(created.node_id, "node-448")
        self.assertEqual(created.source_onboarding_session_id, "sess-448")
        self.assertEqual(created.trust_status, "approved")
        self.assertEqual(created.node_name, "kitchen-node")

        api_payload = created.to_api_dict()
        self.assertEqual(api_payload["requested_node_name"], "kitchen-node")
        self.assertEqual(api_payload["requested_node_type"], "ai-node")
        self.assertEqual(api_payload["requested_node_software_version"], "2.0.0")


if __name__ == "__main__":
    unittest.main()

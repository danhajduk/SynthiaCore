import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.system.onboarding.sessions import NodeOnboardingSessionsStore


class TestNodeOnboardingSessionsStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "node_onboarding_sessions.json"
        self.store = NodeOnboardingSessionsStore(path=self.path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_start_session_persists_required_fields(self) -> None:
        session = self.store.start_session(
            node_nonce="nonce-1",
            requested_node_name="office-node",
            requested_node_type="ai-node",
            requested_node_software_version="0.1.0",
            requested_hostname="node-host",
            requested_ui_endpoint="http://node-host:8765/ui",
            requested_from_ip="10.0.0.22",
            request_metadata={"agent": "ai-node"},
            ttl_seconds=1200,
        )

        self.assertEqual(session.session_state, "pending")
        self.assertEqual(session.node_nonce, "nonce-1")
        self.assertEqual(session.requested_node_name, "office-node")
        self.assertEqual(session.requested_node_type, "ai-node")
        self.assertEqual(session.requested_node_software_version, "0.1.0")
        self.assertEqual(session.requested_hostname, "node-host")
        self.assertEqual(session.requested_ui_endpoint, "http://node-host:8765/ui")
        self.assertEqual(session.requested_from_ip, "10.0.0.22")
        self.assertEqual(session.request_metadata["agent"], "ai-node")
        self.assertIsNone(session.approved_at)
        self.assertIsNone(session.rejected_at)
        self.assertGreaterEqual(len(session.state_history), 1)
        self.assertTrue(self.path.exists())

    def test_load_restores_saved_session(self) -> None:
        created = self.store.start_session(
            node_nonce="nonce-2",
            requested_node_name="lab-node",
            requested_node_type="ai-node",
            requested_node_software_version="0.2.0",
            ttl_seconds=300,
        )

        reloaded = NodeOnboardingSessionsStore(path=self.path).get(created.session_id)
        self.assertEqual(reloaded.session_id, created.session_id)
        self.assertEqual(reloaded.node_nonce, "nonce-2")
        self.assertEqual(reloaded.session_state, "pending")

    def test_approve_transition_records_actor_and_linked_node(self) -> None:
        session = self.store.start_session(
            node_nonce="nonce-3",
            requested_node_name="garage-node",
            requested_node_type="ai-node",
            requested_node_software_version="0.3.0",
        )

        approved = self.store.approve_session(
            session.session_id,
            approved_by_user_id="admin:alice",
            linked_node_id="node-001",
        )

        self.assertEqual(approved.session_state, "approved")
        self.assertEqual(approved.approved_by_user_id, "admin:alice")
        self.assertEqual(approved.linked_node_id, "node-001")
        self.assertIsNotNone(approved.approved_at)

    def test_reject_transition_records_reason(self) -> None:
        session = self.store.start_session(
            node_nonce="nonce-4",
            requested_node_name="kitchen-node",
            requested_node_type="ai-node",
            requested_node_software_version="0.4.0",
        )

        rejected = self.store.reject_session(
            session.session_id,
            rejected_by_user_id="admin:bob",
            rejection_reason="Unrecognized device",
        )
        self.assertEqual(rejected.session_state, "rejected")
        self.assertEqual(rejected.rejection_reason, "Unrecognized device")
        self.assertIsNotNone(rejected.rejected_at)

    def test_cannot_reject_after_approve(self) -> None:
        session = self.store.start_session(
            node_nonce="nonce-5",
            requested_node_name="studio-node",
            requested_node_type="ai-node",
            requested_node_software_version="0.5.0",
        )
        self.store.approve_session(
            session.session_id,
            approved_by_user_id="admin:alice",
            linked_node_id="node-005",
        )
        with self.assertRaisesRegex(ValueError, "invalid_state_transition"):
            self.store.reject_session(session.session_id, rejected_by_user_id="admin:bob")

    def test_consume_requires_approved_and_is_one_time(self) -> None:
        session = self.store.start_session(
            node_nonce="nonce-6",
            requested_node_name="hall-node",
            requested_node_type="ai-node",
            requested_node_software_version="0.6.0",
        )
        with self.assertRaisesRegex(ValueError, "invalid_state_transition"):
            self.store.consume_final_payload(session.session_id)

        self.store.approve_session(
            session.session_id,
            approved_by_user_id="admin:alice",
            linked_node_id="node-006",
        )
        consumed = self.store.consume_final_payload(session.session_id)
        self.assertEqual(consumed.session_state, "consumed")
        self.assertIsNotNone(consumed.final_payload_consumed_at)

        with self.assertRaisesRegex(ValueError, "final_payload_already_consumed"):
            self.store.consume_final_payload(session.session_id)

    def test_expire_stale_pending_sessions(self) -> None:
        stale = self.store.start_session(
            node_nonce="nonce-7",
            requested_node_name="patio-node",
            requested_node_type="ai-node",
            requested_node_software_version="0.7.0",
            ttl_seconds=1,
        )
        future_now = datetime.now(timezone.utc) + timedelta(seconds=5)
        changed = self.store.expire_stale_sessions(now=future_now)

        self.assertEqual(changed, 1)
        refreshed = self.store.get(stale.session_id)
        self.assertEqual(refreshed.session_state, "expired")

    def test_find_active_by_node_nonce_excludes_terminal_or_expired(self) -> None:
        pending = self.store.start_session(
            node_nonce="nonce-8",
            requested_node_name="livingroom-node",
            requested_node_type="ai-node",
            requested_node_software_version="0.8.0",
            ttl_seconds=1200,
        )
        active = self.store.find_active_by_node_nonce("nonce-8")
        self.assertIsNotNone(active)
        self.assertEqual(active.session_id, pending.session_id)

        self.store.approve_session(
            pending.session_id,
            approved_by_user_id="admin:alice",
            linked_node_id="node-008",
        )
        self.store.consume_final_payload(pending.session_id)
        self.assertIsNone(self.store.find_active_by_node_nonce("nonce-8"))

    def test_approve_reject_blocked_after_expiry(self) -> None:
        session = self.store.start_session(
            node_nonce="nonce-9",
            requested_node_name="deck-node",
            requested_node_type="ai-node",
            requested_node_software_version="0.9.0",
            ttl_seconds=1,
        )
        future_now = datetime.now(timezone.utc) + timedelta(seconds=5)
        self.store.expire_stale_sessions(now=future_now)
        with self.assertRaisesRegex(ValueError, "invalid_state_transition"):
            self.store.approve_session(
                session.session_id,
                approved_by_user_id="admin:alice",
                linked_node_id="node-009",
            )
        with self.assertRaisesRegex(ValueError, "invalid_state_transition"):
            self.store.reject_session(
                session.session_id,
                rejected_by_user_id="admin:bob",
            )

    def test_archive_and_prune_terminal_sessions(self) -> None:
        session = self.store.start_session(
            node_nonce="nonce-10",
            requested_node_name="shed-node",
            requested_node_type="ai-node",
            requested_node_software_version="1.0.0",
        )
        self.store.reject_session(session.session_id, rejected_by_user_id="admin:bob", rejection_reason="test")
        now = datetime.now(timezone.utc) + timedelta(days=35)
        archived = self.store.archive_and_prune_terminal_sessions(retain_days=30, now=now)
        self.assertEqual(archived, 1)
        with self.assertRaisesRegex(KeyError, "session_not_found"):
            self.store.get(session.session_id)

    def test_multinode_type_session_lifecycle_supported(self) -> None:
        session = self.store.start_session(
            node_nonce="nonce-11",
            requested_node_name="sensor-east",
            requested_node_type="sensor-node",
            requested_node_software_version="3.0.0",
        )
        self.assertEqual(session.requested_node_type, "sensor-node")
        approved = self.store.approve_session(
            session.session_id,
            approved_by_user_id="admin:global",
            linked_node_id="sensor-001",
        )
        self.assertEqual(approved.session_state, "approved")
        self.assertEqual(approved.linked_node_id, "sensor-001")
        consumed = self.store.consume_final_payload(session.session_id)
        self.assertEqual(consumed.session_state, "consumed")


if __name__ == "__main__":
    unittest.main()

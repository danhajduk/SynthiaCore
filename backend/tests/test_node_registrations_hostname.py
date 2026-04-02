from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.system.onboarding import NodeOnboardingSessionsStore, NodeRegistrationsStore


class TestNodeRegistrationsHostname(unittest.TestCase):
    def test_approved_session_persists_requested_hostname(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions = NodeOnboardingSessionsStore(path=Path(tmpdir) / "node_onboarding_sessions.json")
            registrations = NodeRegistrationsStore(path=Path(tmpdir) / "node_registrations.json")
            session = sessions.start_session(
                node_nonce="nonce-hostname",
                requested_node_name="office-node",
                requested_node_type="ai",
                requested_node_software_version="1.0.0",
                requested_hostname="office-node.local",
                requested_ui_endpoint="http://office-node.local:8765/ui",
                requested_api_base_url="http://office-node.local:8081",
            )
            approved = sessions.approve_session(
                session.session_id,
                approved_by_user_id="admin",
                linked_node_id="node-office",
            )

            record = registrations.upsert_from_approved_session(approved)

            self.assertEqual(record.requested_hostname, "office-node.local")
            self.assertEqual(record.requested_ui_endpoint, "http://office-node.local:8765/ui")
            self.assertEqual(record.requested_api_base_url, "http://office-node.local:8081")
            self.assertEqual(record.api_base_url, "http://office-node.local:8081/api")
            stored = registrations.get("node-office")
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored.requested_hostname, "office-node.local")
            self.assertEqual(stored.requested_ui_endpoint, "http://office-node.local:8765/ui")
            self.assertEqual(stored.requested_api_base_url, "http://office-node.local:8081")
            self.assertEqual(stored.api_base_url, "http://office-node.local:8081/api")


if __name__ == "__main__":
    unittest.main()

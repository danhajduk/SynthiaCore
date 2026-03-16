from __future__ import annotations

import unittest

from app.nodes import NodeRegistry
from app.system.onboarding import NodeRegistrationRecord, NodeRegistrationsStore


class _FakeGovernanceStatus:
    active_governance_version = "gov-1"
    last_issued_timestamp = "2026-03-16T00:00:00Z"
    last_refresh_request_timestamp = "2026-03-16T00:01:00Z"


class _FakeGovernanceService:
    def get_status(self, node_id: str):
        return _FakeGovernanceStatus()


class TestNodesRegistryDomain(unittest.TestCase):
    def test_registry_returns_canonical_node_record(self) -> None:
        store = NodeRegistrationsStore(path=None)
        store._records_by_node = {
            "node-1": NodeRegistrationRecord(
                node_id="node-1",
                node_type="ai",
                node_name="edge-a",
                node_software_version="1.0.0",
                requested_node_type="ai-node",
                capabilities_summary=[],
                trust_status="trusted",
                source_onboarding_session_id="sess-1",
                approved_by_user_id="admin",
                approved_at="2026-03-16T00:00:00Z",
                created_at="2026-03-16T00:00:00Z",
                updated_at="2026-03-16T00:00:00Z",
                declared_capabilities=["inference.text"],
                enabled_providers=["openai"],
                capability_profile_id="cap-node-1-v1",
                capability_declaration_version="1.0",
                capability_declaration_timestamp="2026-03-16T00:00:00Z",
            )
        }
        registry = NodeRegistry(store, _FakeGovernanceService())

        item = registry.get("node-1")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.node_id, "node-1")
        self.assertEqual(item.capabilities.capability_profile_id, "cap-node-1-v1")
        self.assertEqual(item.capabilities.taxonomy.activation.stage, "operational")
        self.assertEqual(item.capabilities.taxonomy.categories[0].category_id, "task_families")
        self.assertEqual(item.status.trust_status, "trusted")
        self.assertTrue(item.status.operational_ready)


if __name__ == "__main__":
    unittest.main()

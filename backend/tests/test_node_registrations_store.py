import json
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
            requested_node_type="ai-node",
            capabilities_summary=["vision", "alerts"],
            trust_status="approved",
            source_onboarding_session_id="sess-001",
            approved_by_user_id="admin:alice",
            approved_at="2026-03-11T00:00:00+00:00",
            created_at="2026-03-11T00:00:00+00:00",
            updated_at="2026-03-11T00:00:00+00:00",
            declared_capabilities=["task.classification", "task.captioning"],
            enabled_providers=["openai", "local-cpu"],
            provider_intelligence=[
                {
                    "provider": "openai",
                    "available_models": [
                        {"model_id": "gpt-4o-mini", "pricing": {"input_per_1k": 0.00015}, "latency_metrics": {"p50_ms": 120.0}}
                    ],
                }
            ],
            capability_declaration_version="1.0",
            capability_declaration_timestamp="2026-03-11T00:00:05+00:00",
            capability_profile_id="cap-node-001-v1",
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
        self.assertEqual(by_id.declared_capabilities, ["task.classification", "task.captioning"])
        self.assertEqual(by_id.enabled_providers, ["openai", "local-cpu"])
        self.assertEqual(by_id.provider_intelligence[0]["provider"], "openai")
        self.assertEqual(by_id.capability_declaration_version, "1.0")
        self.assertEqual(by_id.capability_profile_id, "cap-node-001-v1")
        self.assertFalse(by_id.ui_enabled)
        self.assertIsNone(by_id.ui_base_url)
        self.assertEqual(by_id.ui_mode, "spa")
        self.assertIsNone(by_id.ui_health_endpoint)
        self.assertIsNone(by_id.api_base_url)
        by_session = reloaded.get_by_session("sess-001")
        self.assertIsNotNone(by_session)
        assert by_session is not None
        self.assertEqual(by_session.node_id, "node-001")

    def test_backward_compatible_load_without_capability_metadata(self) -> None:
        payload = {
            "schema_version": "1",
            "items": [
                {
                    "node_id": "node-legacy",
                    "node_type": "ai-node",
                    "node_name": "legacy",
                    "node_software_version": "0.9.0",
                    "trust_status": "trusted",
                    "created_at": "2026-03-11T00:00:00+00:00",
                    "updated_at": "2026-03-11T00:00:00+00:00",
                }
            ],
            "session_to_node": {},
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        reloaded = NodeRegistrationsStore(path=self.path)
        item = reloaded.get("node-legacy")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.declared_capabilities, [])
        self.assertEqual(item.enabled_providers, [])
        self.assertEqual(item.provider_intelligence, [])
        self.assertIsNone(item.capability_declaration_version)
        self.assertIsNone(item.capability_declaration_timestamp)
        self.assertIsNone(item.capability_profile_id)
        self.assertFalse(item.ui_enabled)
        self.assertIsNone(item.ui_base_url)
        self.assertEqual(item.ui_mode, "spa")
        self.assertIsNone(item.ui_health_endpoint)
        self.assertIsNone(item.api_base_url)

    def test_backward_compatible_load_derives_ui_metadata_from_legacy_fields(self) -> None:
        payload = {
            "schema_version": "2",
            "items": [
                {
                    "node_id": "node-ui-legacy",
                    "node_type": "ai-node",
                    "node_name": "legacy-ui",
                    "node_software_version": "0.9.1",
                    "requested_hostname": "legacy-ui.local",
                    "requested_ui_endpoint": "http://legacy-ui.local:8765/ui",
                    "trust_status": "approved",
                    "created_at": "2026-03-11T00:00:00+00:00",
                    "updated_at": "2026-03-11T00:00:00+00:00",
                }
            ],
            "session_to_node": {},
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        reloaded = NodeRegistrationsStore(path=self.path)
        item = reloaded.get("node-ui-legacy")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertTrue(item.ui_enabled)
        self.assertEqual(item.ui_base_url, "http://legacy-ui.local:8765/ui")
        self.assertEqual(item.ui_mode, "spa")
        self.assertIsNone(item.ui_health_endpoint)
        self.assertEqual(item.api_base_url, "http://legacy-ui.local:8765/api")

    def test_upsert_from_approved_session_binds_session_mapping(self) -> None:
        session = NodeOnboardingSession(
            session_id="sess-448",
            session_state="approved",
            node_nonce="nonce-1",
            requested_node_name="kitchen-node",
            requested_node_type="ai-node",
            requested_node_software_version="2.0.0",
            requested_hostname=None,
            requested_ui_endpoint=None,
            requested_api_base_url=None,
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
        self.assertFalse(created.ui_enabled)
        self.assertIsNone(created.ui_base_url)
        self.assertEqual(created.ui_mode, "spa")
        self.assertIsNone(created.api_base_url)

        api_payload = created.to_api_dict()
        self.assertEqual(api_payload["requested_node_name"], "kitchen-node")
        self.assertEqual(api_payload["requested_node_type"], "ai-node")
        self.assertEqual(api_payload["requested_node_software_version"], "2.0.0")
        self.assertFalse(api_payload["ui_enabled"])
        self.assertIsNone(api_payload["ui_base_url"])
        self.assertEqual(api_payload["ui_mode"], "spa")
        self.assertIsNone(api_payload["api_base_url"])

    def test_upsert_from_approved_session_derives_ui_metadata(self) -> None:
        session = NodeOnboardingSession(
            session_id="sess-ui",
            session_state="approved",
            node_nonce="nonce-ui",
            requested_node_name="ui-node",
            requested_node_type="ai-node",
            requested_node_software_version="2.1.0",
            requested_hostname="ui-node.local",
            requested_ui_endpoint="http://ui-node.local:8765/ui",
            requested_api_base_url="http://ui-node.local:8081",
            requested_from_ip=None,
            request_metadata={},
            created_at="2026-03-11T00:00:00+00:00",
            expires_at="2026-03-11T00:15:00+00:00",
            approved_at="2026-03-11T00:01:00+00:00",
            rejected_at=None,
            approved_by_user_id="admin:bob",
            rejection_reason=None,
            linked_node_id="node-ui",
            final_payload_consumed_at=None,
            state_history=[],
        )

        created = self.store.upsert_from_approved_session(session)
        self.assertTrue(created.ui_enabled)
        self.assertEqual(created.ui_base_url, "http://ui-node.local:8765/ui")
        self.assertEqual(created.ui_mode, "spa")
        self.assertIsNone(created.ui_health_endpoint)
        self.assertEqual(created.api_base_url, "http://ui-node.local:8081/api")

    def test_upsert_from_approved_session_derives_ui_base_from_api_base_url_when_ui_missing(self) -> None:
        session = NodeOnboardingSession(
            session_id="sess-api-ui",
            session_state="approved",
            node_nonce="nonce-api-ui",
            requested_node_name="email-node",
            requested_node_type="email-node",
            requested_node_software_version="0.1.0",
            requested_hostname="10.0.0.100",
            requested_ui_endpoint=None,
            requested_api_base_url="http://10.0.0.100:9003/api",
            requested_from_ip=None,
            request_metadata={},
            created_at="2026-03-11T00:00:00+00:00",
            expires_at="2026-03-11T00:15:00+00:00",
            approved_at="2026-03-11T00:01:00+00:00",
            rejected_at=None,
            approved_by_user_id="admin:bob",
            rejection_reason=None,
            linked_node_id="node-email",
            final_payload_consumed_at=None,
            state_history=[],
        )

        created = self.store.upsert_from_approved_session(session)
        self.assertTrue(created.ui_enabled)
        self.assertEqual(created.ui_base_url, "http://10.0.0.100:9003")
        self.assertEqual(created.api_base_url, "http://10.0.0.100:9003/api")

    def test_load_repairs_legacy_hostname_only_ui_base_when_api_base_has_port(self) -> None:
        payload = {
            "field_aliases": {},
            "schema_version": "4",
            "session_to_node": {},
            "items": [
                {
                    "node_id": "node-email",
                    "node_name": "Email Node",
                    "node_type": "email",
                    "node_software_version": "0.1.0",
                    "requested_node_type": "email-node",
                    "requested_hostname": "10.0.0.100",
                    "requested_ui_endpoint": None,
                    "requested_api_base_url": "http://10.0.0.100:9003/api",
                    "ui_enabled": True,
                    "ui_base_url": "http://10.0.0.100",
                    "ui_mode": "spa",
                    "ui_health_endpoint": None,
                    "api_base_url": "http://10.0.0.100:9003/api",
                    "capabilities_summary": [],
                    "trust_status": "trusted",
                    "source_onboarding_session_id": "sess-email",
                    "approved_by_user_id": "admin",
                    "approved_at": "2026-03-11T00:01:00+00:00",
                    "created_at": "2026-03-11T00:00:00+00:00",
                    "updated_at": "2026-03-11T00:01:00+00:00",
                }
            ],
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        reloaded = NodeRegistrationsStore(path=self.path)
        item = reloaded.get("node-email")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.ui_base_url, "http://10.0.0.100:9003")
        self.assertEqual(item.api_base_url, "http://10.0.0.100:9003/api")

    def test_mark_trusted_by_session(self) -> None:
        record = NodeRegistrationRecord(
            node_id="node-910",
            node_type="sensor-node",
            node_name="sensor-north",
            node_software_version="4.2.1",
            requested_node_type="sensor-node",
            capabilities_summary=[],
            trust_status="approved",
            source_onboarding_session_id="sess-910",
            approved_by_user_id="admin:carol",
            approved_at="2026-03-11T00:00:00+00:00",
            created_at="2026-03-11T00:00:00+00:00",
            updated_at="2026-03-11T00:00:00+00:00",
        )
        self.store.upsert(record)
        updated = self.store.mark_trusted_by_session("sess-910")
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.trust_status, "trusted")

    def test_set_trust_status_rejects_invalid_values(self) -> None:
        record = NodeRegistrationRecord(
            node_id="node-911",
            node_type="ai-node",
            node_name="vision-911",
            node_software_version="1.0.0",
            requested_node_type="ai-node",
            capabilities_summary=[],
            trust_status="approved",
            source_onboarding_session_id="sess-911",
            approved_by_user_id="admin",
            approved_at="2026-03-11T00:00:00+00:00",
            created_at="2026-03-11T00:00:00+00:00",
            updated_at="2026-03-11T00:00:00+00:00",
        )
        self.store.upsert(record)
        with self.assertRaisesRegex(ValueError, "trust_status_invalid"):
            self.store.set_trust_status("node-911", trust_status="invalid-state")


if __name__ == "__main__":
    unittest.main()

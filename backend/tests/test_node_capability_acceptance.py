import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.system.onboarding.capability_acceptance import NodeCapabilityAcceptanceService
from app.system.onboarding.capability_profiles import NodeCapabilityProfilesStore


class TestNodeCapabilityAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.profiles = NodeCapabilityProfilesStore(path=Path(self.tmpdir.name) / "profiles.json")
        self.service = NodeCapabilityAcceptanceService(self.profiles)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _manifest(self) -> dict:
        return {
            "manifest_version": "1.0",
            "node": {
                "node_id": "node-abc123",
                "node_type": "ai-node",
                "node_name": "main-ai-node",
                "node_software_version": "0.2.0",
            },
            "declared_task_families": ["task.classification", "task.summarization"],
            "supported_providers": ["openai", "local-llm"],
            "enabled_providers": ["openai"],
            "node_features": {"telemetry": True, "governance_refresh": True},
            "environment_hints": {},
        }

    def test_accepts_valid_manifest(self) -> None:
        result = self.service.evaluate(node_id="node-abc123", manifest=self._manifest())
        self.assertTrue(result.accepted)
        self.assertIsNotNone(result.profile)
        assert result.profile is not None
        self.assertTrue(result.profile.profile_id.startswith("cap-node-abc123-v"))

    def test_rejects_unsupported_task_family(self) -> None:
        manifest = self._manifest()
        manifest["declared_task_families"] = ["task.classification", "task.unknown"]
        with patch.dict(os.environ, {"SYNTHIA_NODE_ALLOWED_TASK_FAMILIES": "task.classification"}, clear=False):
            result = self.service.evaluate(node_id="node-abc123", manifest=manifest)
        self.assertFalse(result.accepted)
        self.assertEqual(result.error_code, "unsupported_task_family")

    def test_rejects_unsupported_provider_identifier(self) -> None:
        manifest = self._manifest()
        manifest["supported_providers"] = ["openai", "provider-x"]
        with patch.dict(os.environ, {"SYNTHIA_NODE_ALLOWED_PROVIDERS": "openai,local-llm"}, clear=False):
            result = self.service.evaluate(node_id="node-abc123", manifest=manifest)
        self.assertFalse(result.accepted)
        self.assertEqual(result.error_code, "unsupported_provider_identifier")


if __name__ == "__main__":
    unittest.main()

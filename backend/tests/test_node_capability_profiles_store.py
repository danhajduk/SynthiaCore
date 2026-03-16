import tempfile
import unittest
from pathlib import Path

from app.system.onboarding.capability_profiles import NodeCapabilityProfilesStore


class TestNodeCapabilityProfilesStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "node_capability_profiles.json"
        self.store = NodeCapabilityProfilesStore(path=self.path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _manifest(self, providers: list[str] | None = None) -> dict:
        return {
            "manifest_version": "1.0",
            "node": {"node_id": "node-abc123", "node_type": "ai-node", "node_name": "n1", "node_software_version": "0.2.0"},
            "declared_task_families": ["task.classification"],
            "supported_providers": ["openai", "local-llm"],
            "enabled_providers": list(providers or ["openai"]),
            "provider_intelligence": [
                {
                    "provider": "openai",
                    "available_models": [
                        {"model_id": "gpt-4o-mini", "pricing": {"input_per_1k": 0.00015}, "latency_metrics": {"p50_ms": 120.0}}
                    ],
                }
            ],
            "node_features": {"telemetry": True},
            "environment_hints": {},
        }

    def test_create_or_get_reuses_profile_for_same_manifest(self) -> None:
        profile1 = self.store.create_or_get(
            node_id="node-abc123",
            manifest=self._manifest(),
            declared_task_families=["task.classification"],
            enabled_providers=["openai"],
            feature_flags={"telemetry": True},
            manifest_version="1.0",
            provider_intelligence=self._manifest()["provider_intelligence"],
        )
        profile2 = self.store.create_or_get(
            node_id="node-abc123",
            manifest=self._manifest(),
            declared_task_families=["task.classification"],
            enabled_providers=["openai"],
            feature_flags={"telemetry": True},
            manifest_version="1.0",
            provider_intelligence=self._manifest()["provider_intelligence"],
        )
        self.assertEqual(profile1.profile_id, profile2.profile_id)
        self.assertEqual(profile1.provider_intelligence[0]["provider"], "openai")
        self.assertEqual(profile1.to_dict()["capability_taxonomy"]["activation"]["stage"], "profile_accepted")
        self.assertEqual(len(self.store.list(node_id="node-abc123")), 1)

    def test_create_or_get_versions_profiles_on_manifest_change(self) -> None:
        p1 = self.store.create_or_get(
            node_id="node-abc123",
            manifest=self._manifest(["openai"]),
            declared_task_families=["task.classification"],
            enabled_providers=["openai"],
            feature_flags={"telemetry": True},
            manifest_version="1.0",
            provider_intelligence=self._manifest(["openai"])["provider_intelligence"],
        )
        p2 = self.store.create_or_get(
            node_id="node-abc123",
            manifest=self._manifest(["local-llm"]),
            declared_task_families=["task.classification"],
            enabled_providers=["local-llm"],
            feature_flags={"telemetry": True},
            manifest_version="1.0",
            provider_intelligence=[
                {
                    "provider": "local-llm",
                    "available_models": [
                        {"model_id": "llama3", "pricing": {"input_per_1k": 0.0}, "latency_metrics": {"p50_ms": 95.0}}
                    ],
                }
            ],
        )
        self.assertNotEqual(p1.profile_id, p2.profile_id)
        self.assertTrue(p1.profile_id.endswith("-v1"))
        self.assertTrue(p2.profile_id.endswith("-v2"))
        self.assertEqual(self.store.latest_for_node("node-abc123").profile_id, p2.profile_id)  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()

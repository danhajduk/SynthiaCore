from __future__ import annotations

import unittest

from app.store.models import AddonManifest, ReleaseManifest


class TestReleaseManifestCompatibilityAdapter(unittest.TestCase):
    def test_release_manifest_accepts_runtime_defaults_ports(self) -> None:
        manifest = ReleaseManifest(
            id="addon_ports",
            name="Addon Ports",
            version="1.0.0",
            core_min_version="0.1.0",
            core_max_version=None,
            dependencies=[],
            conflicts=[],
            checksum="abc123",
            publisher_id="pub-1",
            package_profile="standalone_service",
            runtime_defaults={
                "bind_localhost": False,
                "ports": [{"host": 18081, "container": 8080, "proto": "tcp", "purpose": "http_api"}],
            },
            permissions=["filesystem.read"],
            compatibility={
                "core_min_version": "0.1.0",
                "core_max_version": None,
                "dependencies": [],
                "conflicts": [],
            },
        )
        self.assertIsNotNone(manifest.runtime_defaults)
        assert manifest.runtime_defaults is not None
        self.assertFalse(manifest.runtime_defaults.bind_localhost)
        self.assertEqual(len(manifest.runtime_defaults.ports), 1)
        self.assertEqual(manifest.runtime_defaults.ports[0].host, 18081)
        self.assertEqual(manifest.runtime_defaults.ports[0].container, 8080)
        self.assertEqual(manifest.runtime_defaults.ports[0].proto, "tcp")

    def test_legacy_top_level_fields_backfill_nested_compatibility(self) -> None:
        manifest = ReleaseManifest(
            id="addon_x",
            name="Addon X",
            version="1.0.0",
            core_min_version="0.1.0",
            core_max_version="0.3.0",
            dependencies=["dep_a"],
            conflicts=["bad_a"],
            checksum="abc123",
            publisher_id="pub-1",
            permissions=["filesystem.read"],
            signature={"publisher_id": "pub-1", "signature": "c2ln"},
        )
        self.assertEqual(manifest.compatibility.core_min_version, "0.1.0")
        self.assertEqual(manifest.compatibility.core_max_version, "0.3.0")
        self.assertEqual(manifest.compatibility.dependencies, ["dep_a"])
        self.assertEqual(manifest.compatibility.conflicts, ["bad_a"])

    def test_nested_compatibility_is_canonical(self) -> None:
        manifest = ReleaseManifest(
            id="addon_y",
            name="Addon Y",
            version="1.0.0",
            core_min_version="0.0.1",
            core_max_version="0.9.9",
            dependencies=["wrong_dep"],
            conflicts=["wrong_conflict"],
            checksum="abc123",
            publisher_id="pub-1",
            permissions=["filesystem.read"],
            signature={"publisher_id": "pub-1", "signature": "c2ln"},
            compatibility={
                "core_min_version": "0.2.0",
                "core_max_version": "0.4.0",
                "dependencies": ["dep_real"],
                "conflicts": ["conflict_real"],
            },
        )
        self.assertEqual(manifest.core_min_version, "0.2.0")
        self.assertEqual(manifest.core_max_version, "0.4.0")
        self.assertEqual(manifest.dependencies, ["dep_real"])
        self.assertEqual(manifest.conflicts, ["conflict_real"])

    def test_release_manifest_permission_aliases_are_normalized(self) -> None:
        manifest = ReleaseManifest(
            id="addon_aliases",
            name="Addon Aliases",
            version="1.0.0",
            core_min_version="0.1.0",
            core_max_version=None,
            dependencies=[],
            conflicts=[],
            checksum="abc123",
            publisher_id="pub-1",
            permissions=["network.outbound", "mqtt.client", "network.inbound"],
            signature={"publisher_id": "pub-1", "signature": "c2ln"},
        )
        self.assertEqual(
            manifest.permissions,
            ["network.egress", "mqtt.publish", "mqtt.subscribe", "network.ingress"],
        )

    def test_addon_manifest_permission_aliases_are_normalized(self) -> None:
        manifest = AddonManifest(
            id="addon_aliases",
            name="Addon Aliases",
            version="1.0.0",
            core_min_version="0.1.0",
            core_max_version=None,
            dependencies=[],
            conflicts=[],
            publisher_id="pub-1",
            permissions=["mqtt.client", "network.outbound"],
        )
        self.assertEqual(
            manifest.permissions,
            ["mqtt.publish", "mqtt.subscribe", "network.egress"],
        )

    def test_release_manifest_accepts_semver_suffix_version(self) -> None:
        manifest = ReleaseManifest(
            id="addon_suffix",
            name="Addon Suffix",
            version="0.1.7d",
            core_min_version="0.1.0",
            core_max_version=None,
            dependencies=[],
            conflicts=[],
            checksum="abc123",
            publisher_id="pub-1",
            permissions=["filesystem.read"],
            compatibility={
                "core_min_version": "0.1.0",
                "core_max_version": None,
                "dependencies": [],
                "conflicts": [],
            },
        )
        self.assertEqual(manifest.version, "0.1.7d")

    def test_addon_manifest_version_still_requires_strict_semver(self) -> None:
        with self.assertRaises(ValueError):
            AddonManifest(
                id="addon_bad",
                name="Addon Bad",
                version="0.1.7d",
                core_min_version="0.1.0",
                core_max_version=None,
                dependencies=[],
                conflicts=[],
                publisher_id="pub-1",
                permissions=["filesystem.read"],
            )


if __name__ == "__main__":
    unittest.main()

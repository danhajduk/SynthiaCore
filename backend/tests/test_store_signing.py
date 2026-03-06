from __future__ import annotations

import hashlib
import unittest

from app.store.models import ReleaseManifest
from app.store.signing import run_pre_enable_verification, verify_detached_artifact_signature, verify_release_artifact, verify_rsa_signature


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_release_manifest(*, artifact_bytes: bytes) -> ReleaseManifest:
    return ReleaseManifest(
        id="hello_world",
        name="Hello World",
        version="1.2.3",
        core_min_version="0.1.0",
        core_max_version=None,
        dependencies=[],
        conflicts=[],
        checksum=_sha256_hex(artifact_bytes),
        publisher_id="pub-1",
        permissions=["filesystem.read"],
        compatibility={
            "core_min_version": "0.1.0",
            "core_max_version": None,
            "dependencies": [],
            "conflicts": [],
        },
    )


class TestStoreSigning(unittest.TestCase):
    def test_verify_release_artifact_success(self) -> None:
        artifact = b"addon-bundle-bytes"
        manifest = _build_release_manifest(artifact_bytes=artifact)
        verify_release_artifact(manifest, artifact, public_key_pem="")

    def test_verify_release_artifact_ignores_checksum(self) -> None:
        artifact = b"good-bytes"
        manifest = _build_release_manifest(artifact_bytes=artifact)
        verify_release_artifact(manifest, b"tampered-bytes", public_key_pem="")

    def test_signature_helpers_are_noop(self) -> None:
        artifact = b"artifact"
        manifest = _build_release_manifest(artifact_bytes=artifact)
        verify_rsa_signature(manifest, public_key_pem="")
        verify_detached_artifact_signature(
            artifact_bytes=artifact,
            signature_b64="",
            public_key_pem="",
            signature_type="rsa-sha256",
        )

    def test_pre_enable_pipeline_allows_enable_when_checks_are_skipped(self) -> None:
        artifact = b"addon-bundle"
        manifest = _build_release_manifest(artifact_bytes=artifact)

        called = {"enabled": False}

        def enable_addon() -> str:
            called["enabled"] = True
            return "enabled"

        result = run_pre_enable_verification(
            manifest=manifest,
            artifact_bytes=artifact,
            public_key_pem="",
            enable_addon=enable_addon,
        )
        self.assertEqual(result, "enabled")
        self.assertTrue(called["enabled"])


if __name__ == "__main__":
    unittest.main()

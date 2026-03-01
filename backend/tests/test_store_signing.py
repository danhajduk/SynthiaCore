from __future__ import annotations

import base64
import hashlib
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.store.models import ReleaseManifest
from app.store.signing import (
    VerificationError,
    run_pre_enable_verification,
    verify_detached_artifact_signature,
    verify_release_artifact,
)
import app.store.signing as signing_mod


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_release_manifest(
    *,
    artifact_bytes: bytes,
    signature_b64: str,
    publisher_id: str = "pub-1",
) -> ReleaseManifest:
    return ReleaseManifest(
        id="hello_world",
        name="Hello World",
        version="1.2.3",
        core_min_version="0.1.0",
        core_max_version=None,
        dependencies=[],
        conflicts=[],
        checksum=_sha256_hex(artifact_bytes),
        publisher_id=publisher_id,
        permissions=["filesystem.read"],
        signature={"publisher_id": publisher_id, "signature": signature_b64},
        compatibility={
            "core_min_version": "0.1.0",
            "core_max_version": None,
            "dependencies": [],
            "conflicts": [],
        },
    )


class TestStoreSigning(unittest.TestCase):
    def test_verify_release_artifact_success(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()
        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        artifact = b"addon-bundle-bytes"
        unsigned = _build_release_manifest(artifact_bytes=artifact, signature_b64="a")
        payload = signing_mod._build_signature_payload(unsigned)
        signature = private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
        manifest = _build_release_manifest(
            artifact_bytes=artifact,
            signature_b64=base64.b64encode(signature).decode("ascii"),
        )

        verify_release_artifact(manifest, artifact, public_key_pem)

    def test_verify_release_artifact_rejects_bad_checksum(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        artifact = b"good-bytes"
        unsigned = _build_release_manifest(artifact_bytes=artifact, signature_b64="a")
        payload = signing_mod._build_signature_payload(unsigned)
        signature = private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
        manifest = _build_release_manifest(
            artifact_bytes=artifact,
            signature_b64=base64.b64encode(signature).decode("ascii"),
        )

        with self.assertRaises(VerificationError) as ctx:
            verify_release_artifact(manifest, b"tampered-bytes", public_key_pem)
        self.assertEqual(ctx.exception.code, "checksum_mismatch")

    def test_verify_release_artifact_accepts_escaped_newline_public_key(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        escaped_public_key_pem = public_key_pem.replace("\n", "\\n")

        artifact = b"addon-bundle-bytes-escaped-pem"
        unsigned = _build_release_manifest(artifact_bytes=artifact, signature_b64="a")
        payload = signing_mod._build_signature_payload(unsigned)
        signature = private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
        manifest = _build_release_manifest(
            artifact_bytes=artifact,
            signature_b64=base64.b64encode(signature).decode("ascii"),
        )

        verify_release_artifact(manifest, artifact, escaped_public_key_pem)

    def test_verify_detached_signature_accepts_escaped_newline_public_key(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        escaped_public_key_pem = public_key_pem.replace("\n", "\\n")
        artifact = b"artifact-bytes-detached-escaped-pem"
        signature = private_key.sign(artifact, padding.PKCS1v15(), hashes.SHA256())

        verify_detached_artifact_signature(
            artifact_bytes=artifact,
            signature_b64=base64.b64encode(signature).decode("ascii"),
            public_key_pem=escaped_public_key_pem,
            signature_type="rsa-sha256",
        )

    def test_verify_detached_signature_accepts_ed25519_label_with_compatible_signature(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        artifact = b"artifact-bytes-detached-ed25519-label"
        signature = private_key.sign(artifact, padding.PKCS1v15(), hashes.SHA256())

        verify_detached_artifact_signature(
            artifact_bytes=artifact,
            signature_b64=base64.b64encode(signature).decode("ascii"),
            public_key_pem=public_key_pem,
            signature_type="ed25519",
        )

    def test_pre_enable_pipeline_blocks_enable_on_invalid_signature(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        artifact = b"addon-bundle"
        manifest = _build_release_manifest(
            artifact_bytes=artifact,
            signature_b64=base64.b64encode(b"not-a-valid-signature").decode("ascii"),
        )

        called = {"enabled": False}

        def enable_addon() -> str:
            called["enabled"] = True
            return "enabled"

        with self.assertRaises(VerificationError) as ctx:
            run_pre_enable_verification(
                manifest=manifest,
                artifact_bytes=artifact,
                public_key_pem=public_key_pem,
                enable_addon=enable_addon,
            )
        self.assertEqual(ctx.exception.code, "signature_invalid")
        self.assertFalse(called["enabled"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from synthia_supervisor.crypto import CryptoError, _load_publishers_registry, verify_release_option_a


class TestSynthiaSupervisorCrypto(unittest.TestCase):
    def test_load_publishers_registry_uses_install_root_runtime_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            install_root = Path(tmpdir) / "install"
            fake_module = install_root / "backend" / "synthia_supervisor" / "crypto.py"
            fake_module.parent.mkdir(parents=True, exist_ok=True)

            target = (
                install_root
                / "runtime"
                / "store"
                / "cache"
                / "official"
                / "publishers.json"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"publishers": []}), encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                with patch("synthia_supervisor.crypto.__file__", str(fake_module)):
                    payload = _load_publishers_registry()

        self.assertEqual(payload, {"publishers": []})

    def test_load_publishers_registry_reports_default_path_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            install_root = Path(tmpdir) / "install"
            fake_module = install_root / "backend" / "synthia_supervisor" / "crypto.py"
            fake_module.parent.mkdir(parents=True, exist_ok=True)
            expected = (
                install_root
                / "runtime"
                / "store"
                / "cache"
                / "official"
                / "publishers.json"
            )

            with patch.dict(os.environ, {}, clear=True):
                with patch("synthia_supervisor.crypto.__file__", str(fake_module)):
                    with self.assertRaises(CryptoError) as ctx:
                        _load_publishers_registry()

        self.assertIn(str(expected), str(ctx.exception))

    def test_verify_release_option_a_accepts_legacy_rsa_payload_with_ed25519_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            artifact = tmp / "addon.tgz"
            artifact.write_bytes(b"test-artifact-bytes")
            sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()

            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            signature = key.sign(artifact.read_bytes(), padding.PKCS1v15(), hashes.SHA256())
            signature_b64 = base64.b64encode(signature).decode("ascii")
            public_der = key.public_key().public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )

            publishers = tmp / "publishers.json"
            publishers.write_text(
                json.dumps(
                    {
                        "publishers": [
                            {
                                "keys": [
                                    {
                                        "key_id": "publisher.dan#2026-02",
                                        "status": "active",
                                        "algorithm": "ed25519",
                                        "public_key": base64.b64encode(public_der).decode("ascii"),
                                    }
                                ]
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"SYNTHIA_CATALOG_PUBLISHERS": str(publishers)},
                clear=False,
            ):
                verify_release_option_a(
                    artifact,
                    sha256,
                    signature_b64,
                    "publisher.dan#2026-02",
                    "ed25519",
                )


if __name__ == "__main__":
    unittest.main()

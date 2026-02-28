from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.store.catalog import CatalogCacheClient, CatalogQuery
from app.store.sources import StoreSource


class TestCatalogCacheClient(unittest.TestCase):
    def setUp(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._private_key = private_key
        self._public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    def _source(self) -> StoreSource:
        return StoreSource(
            id="official",
            type="github_raw",
            base_url="https://raw.githubusercontent.test/catalog",
            enabled=True,
            refresh_seconds=300,
        )

    def _sig(self, payload: bytes) -> bytes:
        signature = self._private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
        return base64.b64encode(signature)

    def _client(self, cache_path: Path) -> CatalogCacheClient:
        return CatalogCacheClient(cache_path, catalog_public_keys_json=json.dumps([self._public_key_pem]))

    def test_valid_signature_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            source = self._source()

            payload = json.dumps(
                [
                    {
                        "id": "addon_a",
                        "name": "Addon A",
                        "description": "desc",
                        "categories": ["vision"],
                        "featured": True,
                        "published_at": "2026-02-01T00:00:00Z",
                    }
                ]
            ).encode("utf-8")
            publishers = b'{"publishers":[]}'
            fetch_map = {
                "catalog/v1/index.json": payload,
                "catalog/v1/index.json.sig": self._sig(payload),
                "catalog/v1/publishers.json": publishers,
                "catalog/v1/publishers.json.sig": self._sig(publishers),
            }

            with patch.object(
                CatalogCacheClient,
                "_download_bytes",
                side_effect=lambda url: fetch_map[url.split(source.base_url.rstrip("/") + "/")[1]],
            ):
                refresh = client.refresh_source(source)

            self.assertTrue(refresh["ok"])
            result = client.query_cached(source.id, CatalogQuery())
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["catalog_status"]["status"], "ok")

    def test_invalid_signature_rejected_and_keeps_last_known_good(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            source = self._source()

            good_index = b'[{"id":"addon_a"}]'
            publishers = b'{"publishers":[]}'
            good_fetch = {
                "catalog/v1/index.json": good_index,
                "catalog/v1/index.json.sig": self._sig(good_index),
                "catalog/v1/publishers.json": publishers,
                "catalog/v1/publishers.json.sig": self._sig(publishers),
            }
            with patch.object(
                CatalogCacheClient,
                "_download_bytes",
                side_effect=lambda url: good_fetch[url.split(source.base_url.rstrip("/") + "/")[1]],
            ):
                first = client.refresh_source(source)
            self.assertTrue(first["ok"])

            bad_index = b'[{"id":"addon_b"}]'
            bad_fetch = {
                "catalog/v1/index.json": bad_index,
                "catalog/v1/index.json.sig": b"not-a-valid-signature",
                "catalog/v1/publishers.json": publishers,
                "catalog/v1/publishers.json.sig": self._sig(publishers),
            }
            with patch.object(
                CatalogCacheClient,
                "_download_bytes",
                side_effect=lambda url: bad_fetch[url.split(source.base_url.rstrip("/") + "/")[1]],
            ):
                second = client.refresh_source(source)
            self.assertFalse(second["ok"])

            cached_index = json.loads((Path(td) / source.id / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(cached_index[0]["id"], "addon_a")
            result = client.query_cached(source.id, CatalogQuery())
            self.assertEqual(result["catalog_status"]["status"], "error")
            self.assertEqual(result["catalog_status"]["last_error_message"], "catalog_signature_invalid_encoding")

    def test_missing_signature_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            source = self._source()

            index_payload = b'[{"id":"addon_a"}]'
            publishers = b'{"publishers":[]}'
            missing_sig_fetch = {
                "catalog/v1/index.json": index_payload,
                "catalog/v1/index.json.sig": b"",
                "catalog/v1/publishers.json": publishers,
                "catalog/v1/publishers.json.sig": self._sig(publishers),
            }
            with patch.object(
                CatalogCacheClient,
                "_download_bytes",
                side_effect=lambda url: missing_sig_fetch[url.split(source.base_url.rstrip("/") + "/")[1]],
            ):
                refresh = client.refresh_source(source)

            self.assertFalse(refresh["ok"])
            self.assertEqual(refresh["catalog_status"]["last_error_message"], "catalog_index_signature_missing")


if __name__ == "__main__":
    unittest.main()

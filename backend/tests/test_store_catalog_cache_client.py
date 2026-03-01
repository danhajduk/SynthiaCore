from __future__ import annotations

import base64
import json
import os
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

    def _source(self, base_url: str = "https://raw.githubusercontent.test/catalog") -> StoreSource:
        return StoreSource(
            id="official",
            type="github_raw",
            base_url=base_url,
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
            self.assertEqual(result["catalog_status"]["last_error_message"], "catalog_signature_invalid")

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

    def test_raw_binary_signature_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            source = self._source()

            index_payload = b'[{"id":"addon_raw"}]'
            publishers = b'{"publishers":[]}'
            raw_fetch = {
                "catalog/v1/index.json": index_payload,
                "catalog/v1/index.json.sig": self._private_key.sign(index_payload, padding.PKCS1v15(), hashes.SHA256()),
                "catalog/v1/publishers.json": publishers,
                "catalog/v1/publishers.json.sig": self._private_key.sign(publishers, padding.PKCS1v15(), hashes.SHA256()),
            }
            with patch.object(
                CatalogCacheClient,
                "_download_bytes",
                side_effect=lambda url: raw_fetch[url.split(source.base_url.rstrip("/") + "/")[1]],
            ):
                refresh = client.refresh_source(source)

            self.assertTrue(refresh["ok"])
            result = client.query_cached(source.id, CatalogQuery())
            self.assertEqual(result["catalog_status"]["status"], "ok")
            self.assertEqual(result["items"][0]["id"], "addon_raw")

    def test_official_branch_fallback_on_404(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            source = self._source("https://raw.githubusercontent.test/catalog/main")

            index_payload = b'[{"id":"addon_fallback"}]'
            publishers = b'{"publishers":[]}'
            fetch_map = {
                "catalog/v1/index.json": index_payload,
                "catalog/v1/index.json.sig": self._sig(index_payload),
                "catalog/v1/publishers.json": publishers,
                "catalog/v1/publishers.json.sig": self._sig(publishers),
            }

            def _download(url: str) -> bytes:
                if "/main/" in url:
                    raise RuntimeError("catalog_http_error:404")
                marker = "catalog/v1/"
                if marker not in url:
                    raise RuntimeError("bad_test_url")
                rel = "catalog/v1/" + url.split(marker, 1)[1]
                return fetch_map[rel]

            with patch.object(CatalogCacheClient, "_download_bytes", side_effect=_download):
                refresh = client.refresh_source(source)

            self.assertTrue(refresh["ok"])
            self.assertTrue(str(refresh["catalog_status"].get("resolved_base_url", "")).endswith("/master"))
            result = client.query_cached(source.id, CatalogQuery())
            self.assertEqual(result["catalog_status"]["status"], "ok")
            self.assertEqual(result["items"][0]["id"], "addon_fallback")

    def test_insecure_catalog_bypass_allows_invalid_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            source = self._source()

            index_payload = b'[{"id":"addon_insecure"}]'
            publishers = b'{"publishers":[]}'
            bad_fetch = {
                "catalog/v1/index.json": index_payload,
                "catalog/v1/index.json.sig": b"invalid-signature",
                "catalog/v1/publishers.json": publishers,
                "catalog/v1/publishers.json.sig": b"invalid-signature",
            }

            with patch.dict(os.environ, {"ALLOW_INSECURE_CATALOG": "true"}, clear=False), patch.object(
                CatalogCacheClient,
                "_download_bytes",
                side_effect=lambda url: bad_fetch[url.split(source.base_url.rstrip("/") + "/")[1]],
            ):
                refresh = client.refresh_source(source)

            self.assertTrue(refresh["ok"])
            status = refresh["catalog_status"]
            self.assertEqual(status.get("catalog_integrity_mode"), "insecure_bypass")
            self.assertIn("ALLOW_INSECURE_CATALOG", str(status.get("catalog_integrity_warning")))


if __name__ == "__main__":
    unittest.main()

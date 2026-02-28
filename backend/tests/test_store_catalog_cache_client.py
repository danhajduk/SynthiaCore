from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.store.catalog import CatalogCacheClient, CatalogQuery
from app.store.sources import StoreSource


class TestCatalogCacheClient(unittest.TestCase):
    def _source(self) -> StoreSource:
        return StoreSource(
            id="official",
            type="github_raw",
            base_url="https://raw.githubusercontent.test/catalog",
            enabled=True,
            refresh_seconds=300,
        )

    def test_refresh_and_query_cached_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = CatalogCacheClient(Path(td))
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
            fetch_map = {
                "catalog/v1/index.json": payload,
                "catalog/v1/index.json.sig": b"sig",
                "catalog/v1/publishers.json": b'{"publishers":[]}',
                "catalog/v1/publishers.json.sig": b"sig2",
            }

            with patch.object(CatalogCacheClient, "_download_bytes", side_effect=lambda url: fetch_map[url.split(source.base_url.rstrip('/') + '/')[1]]):
                refresh = client.refresh_source(source)
            self.assertTrue(refresh["ok"])
            result = client.query_cached(source.id, CatalogQuery())
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["catalog_status"]["status"], "ok")

    def test_refresh_failure_keeps_last_known_good(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = CatalogCacheClient(Path(td))
            source = self._source()

            good_fetch = {
                "catalog/v1/index.json": b'[{"id":"addon_a"}]',
                "catalog/v1/index.json.sig": b"sig",
                "catalog/v1/publishers.json": b'{"publishers":[]}',
                "catalog/v1/publishers.json.sig": b"sig2",
            }
            with patch.object(CatalogCacheClient, "_download_bytes", side_effect=lambda url: good_fetch[url.split(source.base_url.rstrip('/') + '/')[1]]):
                first = client.refresh_source(source)
            self.assertTrue(first["ok"])

            bad_fetch = {
                "catalog/v1/index.json": b'[{"id":"addon_b"}]',
                "catalog/v1/index.json.sig": b"",
                "catalog/v1/publishers.json": b'{"publishers":[]}',
                "catalog/v1/publishers.json.sig": b"sig2",
            }
            with patch.object(CatalogCacheClient, "_download_bytes", side_effect=lambda url: bad_fetch[url.split(source.base_url.rstrip('/') + '/')[1]]):
                second = client.refresh_source(source)
            self.assertFalse(second["ok"])

            cached_index = json.loads((Path(td) / source.id / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(cached_index[0]["id"], "addon_a")
            result = client.query_cached(source.id, CatalogQuery())
            self.assertEqual(result["catalog_status"]["status"], "error")
            self.assertIsNotNone(result["catalog_status"]["last_success_at"])


if __name__ == "__main__":
    unittest.main()

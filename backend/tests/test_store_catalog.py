from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.store.catalog import CatalogQuery, StaticCatalogStore


class TestStoreCatalog(unittest.TestCase):
    def _make_store(self) -> StaticCatalogStore:
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "catalog.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "id": "b",
                        "name": "Beta",
                        "description": "beta item",
                        "categories": ["tools"],
                        "featured": False,
                        "published_at": "2026-01-01T00:00:00Z",
                    },
                    {
                        "id": "a",
                        "name": "Alpha",
                        "description": "alpha search target",
                        "categories": ["ai", "tools"],
                        "featured": True,
                        "published_at": "2026-02-01T00:00:00Z",
                    },
                ]
            ),
            encoding="utf-8",
        )
        return StaticCatalogStore(path)

    def tearDown(self) -> None:
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def test_recent_sort_default(self) -> None:
        store = self._make_store()
        res = store.query(CatalogQuery())
        self.assertEqual([x["id"] for x in res["items"]], ["a", "b"])

    def test_search_category_and_featured_filters(self) -> None:
        store = self._make_store()
        res = store.query(CatalogQuery(q="search", category="ai", featured=True))
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["items"][0]["id"], "a")

    def test_pagination(self) -> None:
        store = self._make_store()
        res = store.query(CatalogQuery(page=2, page_size=1, sort="name"))
        self.assertEqual(res["total"], 2)
        self.assertEqual(len(res["items"]), 1)
        self.assertEqual(res["items"][0]["id"], "b")

    def test_returns_structured_error_status_on_invalid_json(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "catalog.json"
        path.write_text("{not valid json", encoding="utf-8")
        store = StaticCatalogStore(path)
        res = store.query(CatalogQuery())
        self.assertEqual(res["catalog_status"]["status"], "error")
        self.assertEqual(res["catalog_status"]["message"], "catalog_read_or_parse_error")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.store.audit import StoreAuditLogStore
from app.store.router import build_store_router
from app.store.sources import OFFICIAL_SOURCE_ID, StoreSourcesStore


class _FakeRegistry:
    def __init__(self) -> None:
        self.addons = {}
        self.enabled = {}

    def is_enabled(self, addon_id: str) -> bool:
        return self.enabled.get(addon_id, True)

    def set_enabled(self, addon_id: str, enabled: bool) -> None:
        self.enabled[addon_id] = enabled


class TestStoreSourcesEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.old_token = os.environ.get("SYNTHIA_ADMIN_TOKEN")
        os.environ["SYNTHIA_ADMIN_TOKEN"] = "test-token"
        self.tmp = tempfile.TemporaryDirectory()
        audit = StoreAuditLogStore(str(Path(self.tmp.name) / "store_audit.db"))
        sources = StoreSourcesStore(str(Path(self.tmp.name) / "store_sources.json"))
        app = FastAPI()
        app.include_router(build_store_router(_FakeRegistry(), audit, sources), prefix="/api/store")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        if self.old_token is None:
            os.environ.pop("SYNTHIA_ADMIN_TOKEN", None)
        else:
            os.environ["SYNTHIA_ADMIN_TOKEN"] = self.old_token

    def test_sources_crud_and_refresh(self) -> None:
        res = self.client.get("/api/store/sources")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertTrue(any(x["id"] == OFFICIAL_SOURCE_ID for x in payload["items"]))

        create = self.client.post(
            "/api/store/sources",
            headers={"X-Admin-Token": "test-token"},
            json={
                "id": "backup",
                "type": "github_raw",
                "base_url": "https://example.com/catalog",
                "enabled": True,
                "refresh_seconds": 600,
            },
        )
        self.assertEqual(create.status_code, 200, create.text)

        refresh = self.client.post(
            "/api/store/sources/backup/refresh",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(refresh.status_code, 200, refresh.text)
        self.assertIsNotNone(refresh.json()["source"]["last_refresh_requested_at"])

        delete = self.client.delete(
            "/api/store/sources/backup",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(delete.status_code, 200, delete.text)

    def test_official_source_delete_is_blocked(self) -> None:
        res = self.client.delete(
            f"/api/store/sources/{OFFICIAL_SOURCE_ID}",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(res.status_code, 400, res.text)


if __name__ == "__main__":
    unittest.main()

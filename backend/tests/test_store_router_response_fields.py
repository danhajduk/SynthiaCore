from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.store.router import AtomicResult, StoreAuditLogStore, build_store_router


class _FakeMeta:
    def __init__(self, version: str = "1.0.0") -> None:
        self.version = version


class _FakeAddon:
    def __init__(self, version: str = "1.0.0") -> None:
        self.meta = _FakeMeta(version=version)


class _FakeRegistry:
    def __init__(self) -> None:
        self.addons = {"hello_world": _FakeAddon("1.0.0")}
        self.enabled: dict[str, bool] = {}

    def is_enabled(self, addon_id: str) -> bool:
        return self.enabled.get(addon_id, True)

    def set_enabled(self, addon_id: str, enabled: bool) -> None:
        self.enabled[addon_id] = enabled


def _manifest_payload(addon_id: str = "hello_world") -> dict:
    return {
        "id": addon_id,
        "name": addon_id,
        "version": "1.0.0",
        "core_min_version": "0.1.0",
        "core_max_version": None,
        "dependencies": [],
        "conflicts": [],
        "checksum": "abc123",
        "publisher_id": "pub-1",
        "permissions": ["filesystem.read"],
        "signature": {"publisher_id": "pub-1", "signature": "c2ln"},
        "compatibility": {
            "core_min_version": "0.1.0",
            "core_max_version": None,
            "dependencies": [],
            "conflicts": [],
        },
    }


class TestStoreRouterResponseFields(unittest.TestCase):
    def test_install_response_includes_registry_and_hot_loaded(self) -> None:
        old_token = os.environ.get("SYNTHIA_ADMIN_TOKEN")
        os.environ["SYNTHIA_ADMIN_TOKEN"] = "test-token"
        try:
            registry = _FakeRegistry()
            with tempfile.TemporaryDirectory() as td:
                db_path = str(Path(td) / "store_audit.db")
                audit_store = StoreAuditLogStore(db_path)
                app = FastAPI()
                app.include_router(build_store_router(registry, audit_store), prefix="/api/store")
                client = TestClient(app)

                package_path = Path(td) / "bundle.zip"
                package_path.write_bytes(b"zip-bytes")

                with patch("app.store.router.verify_release_artifact", return_value=None), patch(
                    "app.store.router.resolve_manifest_compatibility", return_value=None
                ), patch(
                    "app.store.router._atomic_install_or_update",
                    return_value=AtomicResult(
                        addon_dir=Path(td) / "addons" / "hello_world",
                        backup_dir=None,
                        installed_manifest={"id": "hello_world"},
                    ),
                ):
                    res = client.post(
                        "/api/store/install",
                        headers={"X-Admin-Token": "test-token"},
                        json={
                            "package_path": str(package_path),
                            "manifest": _manifest_payload("hello_world"),
                            "public_key_pem": "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----",
                            "enable": True,
                        },
                    )

                self.assertEqual(res.status_code, 200, res.text)
                payload = res.json()
                self.assertIn("registry_loaded", payload)
                self.assertIn("hot_loaded", payload)
                self.assertNotIn("loaded_now", payload)
                self.assertTrue(payload["registry_loaded"])
                self.assertFalse(payload["hot_loaded"])
        finally:
            if old_token is None:
                os.environ.pop("SYNTHIA_ADMIN_TOKEN", None)
            else:
                os.environ["SYNTHIA_ADMIN_TOKEN"] = old_token


if __name__ == "__main__":
    unittest.main()

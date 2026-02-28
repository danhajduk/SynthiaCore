from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.store.router import AtomicResult, StoreAuditLogStore, build_store_router
from app.store.signing import VerificationError
from app.store.sources import StoreSource


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


class _FakeSourcesStore:
    async def list_sources(self):
        return [
            StoreSource(
                id="official",
                type="github_raw",
                base_url="https://raw.githubusercontent.test/catalog",
                enabled=True,
                refresh_seconds=300,
            )
        ]


class _FakeCatalogClient:
    def __init__(self, *, index_payload: dict, publishers_payload: dict, artifact_bytes: bytes) -> None:
        self._index_payload = index_payload
        self._publishers_payload = publishers_payload
        self._artifact_bytes = artifact_bytes

    def select_source(self, sources, source_id):
        for src in sources:
            if src.id == (source_id or "official"):
                return src
        return None

    def load_cached_documents(self, source_id: str):
        if source_id != "official":
            return None, None
        return self._index_payload, self._publishers_payload

    def download_artifact(self, url: str) -> bytes:
        return self._artifact_bytes


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


class TestStoreApiEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.old_token = os.environ.get("SYNTHIA_ADMIN_TOKEN")
        self.old_install_state = os.environ.get("STORE_INSTALL_STATE_PATH")
        os.environ["SYNTHIA_ADMIN_TOKEN"] = "test-token"
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "store_audit.db")
        os.environ["STORE_INSTALL_STATE_PATH"] = str(Path(self.tmp.name) / "store_install_state.json")
        self.registry = _FakeRegistry()
        self.audit = StoreAuditLogStore(self.db_path)
        self.app = FastAPI()
        self.app.include_router(build_store_router(self.registry, self.audit), prefix="/api/store")
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        if self.old_token is None:
            os.environ.pop("SYNTHIA_ADMIN_TOKEN", None)
        else:
            os.environ["SYNTHIA_ADMIN_TOKEN"] = self.old_token
        if self.old_install_state is None:
            os.environ.pop("STORE_INSTALL_STATE_PATH", None)
        else:
            os.environ["STORE_INSTALL_STATE_PATH"] = self.old_install_state

    def test_catalog_endpoint(self) -> None:
        res = self.client.get("/api/store/catalog")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertIn("items", payload)
        self.assertIn("catalog_status", payload)

    def test_install_success_and_invalid_signature(self) -> None:
        pkg = Path(self.tmp.name) / "bundle.zip"
        pkg.write_bytes(b"bytes")

        with patch("app.store.router.verify_release_artifact", return_value=None), patch(
            "app.store.router.resolve_manifest_compatibility", return_value=None
        ), patch(
            "app.store.router._atomic_install_or_update",
            return_value=AtomicResult(
                addon_dir=Path(self.tmp.name) / "addons" / "hello_world",
                backup_dir=None,
                installed_manifest={"id": "hello_world"},
            ),
        ):
            ok_res = self.client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "package_path": str(pkg),
                    "manifest": _manifest_payload(),
                    "public_key_pem": "pem",
                    "enable": True,
                },
            )
        self.assertEqual(ok_res.status_code, 200, ok_res.text)

        with patch(
            "app.store.router.verify_release_artifact",
            side_effect=VerificationError(code="signature_invalid", message="bad sig"),
        ):
            bad_res = self.client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "package_path": str(pkg),
                    "manifest": _manifest_payload(),
                    "public_key_pem": "pem",
                    "enable": True,
                },
            )
        self.assertEqual(bad_res.status_code, 400, bad_res.text)

    def test_status_and_uninstall_not_found(self) -> None:
        with patch("app.store.router._addons_root", return_value=Path(self.tmp.name) / "addons"):
            res = self.client.get("/api/store/status/hello_world")
            self.assertEqual(res.status_code, 200, res.text)
            payload = res.json()
            self.assertIn("installed", payload)
            self.assertIn("installed_from_source_id", payload)
            self.assertIn("installed_release_url", payload)
            self.assertIn("installed_sha256", payload)
            self.assertIn("installed_at", payload)

        uninstall_res = self.client.post(
            "/api/store/uninstall",
            headers={"X-Admin-Token": "test-token"},
            json={"addon_id": "missing-addon"},
        )
        self.assertEqual(uninstall_res.status_code, 404, uninstall_res.text)

    def test_update_success(self) -> None:
        pkg = Path(self.tmp.name) / "bundle.zip"
        pkg.write_bytes(b"bytes")

        with patch("app.store.router.verify_release_artifact", return_value=None), patch(
            "app.store.router.resolve_manifest_compatibility", return_value=None
        ), patch(
            "app.store.router._atomic_install_or_update",
            return_value=AtomicResult(
                addon_dir=Path(self.tmp.name) / "addons" / "hello_world",
                backup_dir=Path(self.tmp.name) / "addons" / ".store_backup" / "x",
                installed_manifest={"id": "hello_world"},
            ),
        ):
            res = self.client.post(
                "/api/store/update",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "package_path": str(pkg),
                    "manifest": _manifest_payload(),
                    "public_key_pem": "pem",
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 200, res.text)

    def test_catalog_install_success_and_status_metadata(self) -> None:
        pkg = Path(self.tmp.name) / "bundle.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()

        index_payload = {
            "addons": [
                {
                    "id": "hello_world",
                    "name": "hello_world",
                    "publisher_id": "pub-1",
                    "permissions": ["filesystem.read"],
                    "releases": [
                        {
                            "version": "1.0.0",
                            "artifact_url": "https://example.test/hello_world-1.0.0.zip",
                            "sha256": "dummy-checksum",
                            "checksum": "dummy-checksum",
                            "release_sig": "c2ln",
                            "compatibility": {
                                "core_min_version": "0.1.0",
                                "core_max_version": None,
                                "dependencies": [],
                                "conflicts": [],
                            },
                        }
                    ],
                }
            ]
        }
        publishers_payload = {
            "publishers": [
                {
                    "id": "pub-1",
                    "enabled": True,
                    "public_key_pem": "pem",
                }
            ]
        }
        fake_catalog = _FakeCatalogClient(
            index_payload=index_payload,
            publishers_payload=publishers_payload,
            artifact_bytes=artifact_bytes,
        )
        app = FastAPI()
        app.include_router(
            build_store_router(
                self.registry,
                self.audit,
                _FakeSourcesStore(),
                fake_catalog,  # type: ignore[arg-type]
            ),
            prefix="/api/store",
        )
        client = TestClient(app)

        with patch("app.store.router.verify_release_artifact", return_value=None), patch(
            "app.store.router.resolve_manifest_compatibility", return_value=None
        ), patch(
            "app.store.router._hex_sha256", return_value="dummy-checksum"
        ), patch(
            "app.store.router._atomic_install_or_update",
            return_value=AtomicResult(
                addon_dir=Path(self.tmp.name) / "addons" / "hello_world",
                backup_dir=None,
                installed_manifest={"id": "hello_world"},
            ),
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world", "enable": True},
            )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["installed_from_source_id"], "official")
        self.assertEqual(payload["installed_release_url"], "https://example.test/hello_world-1.0.0.zip")
        self.assertEqual(payload["installed_sha256"], "dummy-checksum")

        with patch("app.store.router._addons_root", return_value=Path(self.tmp.name) / "addons"):
            status = client.get("/api/store/status/hello_world")
        self.assertEqual(status.status_code, 200, status.text)
        status_payload = status.json()
        self.assertEqual(status_payload["installed_from_source_id"], "official")
        self.assertEqual(status_payload["installed_release_url"], "https://example.test/hello_world-1.0.0.zip")
        self.assertEqual(status_payload["installed_sha256"], "dummy-checksum")
        self.assertIsNotNone(status_payload["installed_at"])


if __name__ == "__main__":
    unittest.main()

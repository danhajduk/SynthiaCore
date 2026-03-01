from __future__ import annotations

import base64
import hashlib
import os
import tarfile
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.store.router import AtomicResult, StoreAuditLogStore, _artifact_temp_filename, build_store_router
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
    def __init__(
        self,
        *,
        index_payload: dict,
        publishers_payload: dict,
        artifact_bytes: bytes,
        fail_first_download_404: bool = False,
        fail_all_download_404: bool = False,
        refreshed_index_payload: dict | None = None,
        refreshed_publishers_payload: dict | None = None,
        resolved_base_url: str = "https://raw.githubusercontent.test/catalog",
    ) -> None:
        self._index_payload = index_payload
        self._publishers_payload = publishers_payload
        self._artifact_bytes = artifact_bytes
        self._fail_first_download_404 = fail_first_download_404
        self._fail_all_download_404 = fail_all_download_404
        self._download_calls = 0
        self._refresh_calls = 0
        self.downloaded_urls: list[str] = []
        self._refreshed_index_payload = refreshed_index_payload
        self._refreshed_publishers_payload = refreshed_publishers_payload
        self._resolved_base_url = resolved_base_url

    def select_source(self, sources, source_id):
        for src in sources:
            if src.id == (source_id or "official"):
                return src
        return None

    def load_cached_documents(self, source_id: str):
        if source_id != "official":
            return None, None
        return self._index_payload, self._publishers_payload

    def refresh_source(self, source):
        self._refresh_calls += 1
        if self._refreshed_index_payload is not None:
            self._index_payload = self._refreshed_index_payload
        if self._refreshed_publishers_payload is not None:
            self._publishers_payload = self._refreshed_publishers_payload
        return {
            "ok": True,
            "source_id": source.id,
            "catalog_status": {"status": "ok", "resolved_base_url": self._resolved_base_url},
        }

    def load_source_metadata(self, source_id: str) -> dict:
        if source_id != "official":
            return {}
        return {"source_id": source_id, "resolved_base_url": self._resolved_base_url}

    def download_artifact(self, url: str) -> bytes:
        self.downloaded_urls.append(url)
        self._download_calls += 1
        if self._fail_all_download_404:
            raise RuntimeError("catalog_http_error:404")
        if self._fail_first_download_404 and self._download_calls == 1:
            raise RuntimeError("catalog_http_error:404")
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
        "package_profile": "embedded_addon",
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
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._private_key = private_key
        self._public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

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

    def _sign_artifact(self, artifact_bytes: bytes) -> str:
        sig = self._private_key.sign(artifact_bytes, padding.PKCS1v15(), hashes.SHA256())
        return base64.b64encode(sig).decode("utf-8")

    def _build_catalog_client(
        self,
        *,
        artifact_bytes: bytes,
        release_sig: str,
        publisher_key_id: str = "key-1",
        publishers_key_id: str = "key-1",
        key_enabled: bool = True,
        signature_type: str = "rsa-sha256",
        use_addon_id_field: bool = False,
        use_publishers_alias_schema: bool = False,
        omit_publisher_id: bool = False,
        use_nested_artifact_url: bool = False,
        core_min_version: str = "0.1.0",
        release_url: str = "https://example.test/hello_world-1.0.0.zip",
        package_profile: str = "embedded_addon",
        use_channels_schema: bool = False,
        use_channels_wrapped_schema: bool = False,
        use_signature_object_schema: bool = False,
        fail_first_download_404: bool = False,
        fail_all_download_404: bool = False,
        refreshed_release_url: str | None = None,
        release_sha256: str | None = None,
        release_checksum: str | None = None,
        release_manifest_package_profile: str | None = None,
        escape_publishers_public_key_pem: bool = False,
    ) -> _FakeCatalogClient:
        digest = hashlib.sha256(artifact_bytes).hexdigest()
        addon_identity = {"addon_id": "hello_world"} if use_addon_id_field else {"id": "hello_world"}
        addon_publisher = {} if omit_publisher_id else {"publisher_id": "pub-1"}
        release_publisher = {} if omit_publisher_id else {"publisher_id": "pub-1"}
        publisher_public_key_pem = (
            self._public_key_pem.replace("\n", "\\n")
            if escape_publishers_public_key_pem
            else self._public_key_pem
        )
        release_payload = {
            "version": "1.0.0",
            "sha256": release_sha256 if release_sha256 is not None else digest,
            "checksum": release_checksum if release_checksum is not None else digest,
            "publisher_key_id": publisher_key_id,
            "package_profile": package_profile,
            **release_publisher,
            "compatibility": {
                "core_min_version": core_min_version,
                "core_max_version": None,
                "dependencies": [],
                "conflicts": [],
            },
        }
        if use_signature_object_schema:
            release_payload["signature"] = {"type": signature_type, "value": release_sig}
        else:
            release_payload["release_sig"] = release_sig
            release_payload["signature_type"] = signature_type
        if release_manifest_package_profile is not None:
            release_payload["manifest"] = {"package_profile": release_manifest_package_profile}
        if use_nested_artifact_url:
            release_payload["artifact"] = {"url": release_url}
        else:
            release_payload["artifact_url"] = release_url
        publisher_record = (
            {
                "publisher_id": "pub-1",
                "status": "enabled",
                "keys": [
                    {
                        "key_id": publishers_key_id,
                        "status": "enabled" if key_enabled else "revoked",
                        "type": signature_type,
                        "public_key_pem": publisher_public_key_pem,
                    }
                ],
            }
            if use_publishers_alias_schema
            else {
                "id": "pub-1",
                "enabled": True,
                "keys": [
                    {
                        "id": publishers_key_id,
                        "enabled": key_enabled,
                        "signature_type": signature_type,
                        "public_key_pem": publisher_public_key_pem,
                    }
                ],
            }
        )
        addon_payload: dict[str, object] = {
            **addon_identity,
            "name": "hello_world",
            **addon_publisher,
            "permissions": ["filesystem.read"],
        }
        if use_channels_schema and use_channels_wrapped_schema:
            addon_payload["channels"] = {"stable": {"releases": [release_payload]}, "beta": [], "nightly": []}
        elif use_channels_schema:
            addon_payload["channels"] = {"stable": [release_payload], "beta": [], "nightly": []}
        else:
            addon_payload["releases"] = [release_payload]

        index_payload = {"addons": [addon_payload]}
        publishers_payload = {
            "publishers": [
                publisher_record
            ]
        }

        refreshed_index_payload: dict | None = None
        if refreshed_release_url:
            refreshed_release = dict(release_payload)
            if use_nested_artifact_url:
                refreshed_release["artifact"] = {"url": refreshed_release_url}
            else:
                refreshed_release["artifact_url"] = refreshed_release_url
            refreshed_addon_payload: dict[str, object] = {
                **addon_identity,
                "name": "hello_world",
                **addon_publisher,
                "permissions": ["filesystem.read"],
            }
            if use_channels_schema and use_channels_wrapped_schema:
                refreshed_addon_payload["channels"] = {"stable": {"releases": [refreshed_release]}, "beta": [], "nightly": []}
            elif use_channels_schema:
                refreshed_addon_payload["channels"] = {"stable": [refreshed_release], "beta": [], "nightly": []}
            else:
                refreshed_addon_payload["releases"] = [refreshed_release]
            refreshed_index_payload = {"addons": [refreshed_addon_payload]}

        return _FakeCatalogClient(
            index_payload=index_payload,
            publishers_payload=publishers_payload,
            artifact_bytes=artifact_bytes,
            fail_first_download_404=fail_first_download_404,
            fail_all_download_404=fail_all_download_404,
            refreshed_index_payload=refreshed_index_payload,
            refreshed_publishers_payload=publishers_payload if refreshed_index_payload is not None else None,
        )

    def test_catalog_endpoint(self) -> None:
        with patch(
            "app.store.router._load_install_state",
            return_value={
                "hello_world": {
                    "installed_version": "1.0.0",
                    "installed_at": "2026-02-28T15:00:00+00:00",
                }
            },
        ):
            res = self.client.get("/api/store/catalog")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertIn("items", payload)
        self.assertIn("catalog_status", payload)
        self.assertIn("installed", payload)
        self.assertEqual(payload["installed"]["hello_world"]["version"], "1.0.0")
        self.assertEqual(payload["installed"]["hello_world"]["installed_at"], "2026-02-28T15:00:00+00:00")

    def test_artifact_temp_filename_infers_tgz_suffix(self) -> None:
        filename = _artifact_temp_filename("https://example.test/releases/download/v1.0.0/addon.tgz")
        self.assertEqual(filename, "artifact.tgz")

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
            self.assertIn("installed_resolved_base_url", payload)
            self.assertIn("installed_release_url", payload)
            self.assertIn("installed_sha256", payload)
            self.assertIn("installed_at", payload)
            self.assertIn("last_install_error", payload)

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
        fake_catalog = self._build_catalog_client(artifact_bytes=artifact_bytes, release_sig=self._sign_artifact(artifact_bytes))
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

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
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
        self.assertEqual(payload["installed_sha256"], hashlib.sha256(artifact_bytes).hexdigest())

        with patch("app.store.router._addons_root", return_value=Path(self.tmp.name) / "addons"):
            status = client.get("/api/store/status/hello_world")
        self.assertEqual(status.status_code, 200, status.text)
        status_payload = status.json()
        self.assertEqual(status_payload["installed_from_source_id"], "official")
        self.assertEqual(status_payload["installed_resolved_base_url"], "https://raw.githubusercontent.test/catalog")
        self.assertEqual(status_payload["installed_release_url"], "https://example.test/hello_world-1.0.0.zip")
        self.assertEqual(status_payload["installed_sha256"], hashlib.sha256(artifact_bytes).hexdigest())
        self.assertIsNotNone(status_payload["installed_at"])
        self.assertIsNone(status_payload["last_install_error"])

    def test_catalog_install_accepts_addon_id_alias(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-alias.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            use_addon_id_field=True,
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

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
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

    def test_catalog_install_accepts_nested_artifact_url(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-nested-artifact.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            use_nested_artifact_url=True,
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
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
        self.assertEqual(res.json()["installed_release_url"], "https://example.test/hello_world-1.0.0.zip")

    def test_catalog_install_accepts_channels_stable_release_schema(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-channels-stable.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            use_channels_schema=True,
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
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
        self.assertEqual(res.json()["installed_release_url"], "https://example.test/hello_world-1.0.0.zip")

    def test_catalog_install_accepts_channels_wrapped_releases_schema(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-channels-wrapped.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            use_channels_schema=True,
            use_channels_wrapped_schema=True,
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
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
        self.assertEqual(res.json()["installed_release_url"], "https://example.test/hello_world-1.0.0.zip")

    def test_catalog_install_prefers_stable_channel_over_newer_beta(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-channels-precedence.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        release_sig = self._sign_artifact(artifact_bytes)
        index_payload = {
            "addons": [
                {
                    "id": "hello_world",
                    "name": "hello_world",
                    "publisher_id": "pub-1",
                    "permissions": ["filesystem.read"],
                    "channels": {
                        "stable": [
                            {
                                "version": "1.0.0",
                                "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
                                "checksum": hashlib.sha256(artifact_bytes).hexdigest(),
                                "publisher_key_id": "key-1",
                                "package_profile": "embedded_addon",
                                "publisher_id": "pub-1",
                                "release_sig": release_sig,
                                "signature_type": "rsa-sha256",
                                "artifact_url": "https://example.test/stable-1.0.0.zip",
                                "compatibility": {
                                    "core_min_version": "0.1.0",
                                    "core_max_version": None,
                                    "dependencies": [],
                                    "conflicts": [],
                                },
                            }
                        ],
                        "beta": [
                            {
                                "version": "9.0.0",
                                "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
                                "checksum": hashlib.sha256(artifact_bytes).hexdigest(),
                                "publisher_key_id": "key-1",
                                "package_profile": "embedded_addon",
                                "publisher_id": "pub-1",
                                "release_sig": release_sig,
                                "signature_type": "rsa-sha256",
                                "artifact_url": "https://example.test/beta-9.0.0.zip",
                                "compatibility": {
                                    "core_min_version": "0.1.0",
                                    "core_max_version": None,
                                    "dependencies": [],
                                    "conflicts": [],
                                },
                            }
                        ],
                        "nightly": [],
                    },
                }
            ]
        }
        publishers_payload = {
            "publishers": [
                {
                    "id": "pub-1",
                    "enabled": True,
                    "keys": [
                        {
                            "id": "key-1",
                            "enabled": True,
                            "signature_type": "rsa-sha256",
                            "public_key_pem": self._public_key_pem,
                        }
                    ],
                }
            ]
        }
        fake_catalog = _FakeCatalogClient(
            index_payload=index_payload,
            publishers_payload=publishers_payload,
            artifact_bytes=artifact_bytes,
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
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
        self.assertEqual(res.json()["installed_release_url"], "https://example.test/stable-1.0.0.zip")

    def test_catalog_install_falls_back_to_beta_when_stable_has_no_compatible_release(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-channels-fallback.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        release_sig = self._sign_artifact(artifact_bytes)
        digest = hashlib.sha256(artifact_bytes).hexdigest()
        index_payload = {
            "addons": [
                {
                    "id": "hello_world",
                    "name": "hello_world",
                    "publisher_id": "pub-1",
                    "permissions": ["filesystem.read"],
                    "channels": {
                        "stable": [
                            {
                                "version": "3.0.0",
                                "sha256": digest,
                                "checksum": digest,
                                "publisher_key_id": "key-1",
                                "package_profile": "embedded_addon",
                                "publisher_id": "pub-1",
                                "release_sig": release_sig,
                                "signature_type": "rsa-sha256",
                                "artifact_url": "https://example.test/stable-3.0.0.zip",
                                "compatibility": {
                                    "core_min_version": "9.0.0",
                                    "core_max_version": None,
                                    "dependencies": [],
                                    "conflicts": [],
                                },
                            }
                        ],
                        "beta": [
                            {
                                "version": "2.0.0",
                                "sha256": digest,
                                "checksum": digest,
                                "publisher_key_id": "key-1",
                                "package_profile": "embedded_addon",
                                "publisher_id": "pub-1",
                                "release_sig": release_sig,
                                "signature_type": "rsa-sha256",
                                "artifact_url": "https://example.test/beta-2.0.0.zip",
                                "compatibility": {
                                    "core_min_version": "0.1.0",
                                    "core_max_version": None,
                                    "dependencies": [],
                                    "conflicts": [],
                                },
                            }
                        ],
                        "nightly": [],
                    },
                }
            ]
        }
        publishers_payload = {
            "publishers": [
                {
                    "id": "pub-1",
                    "enabled": True,
                    "keys": [
                        {
                            "id": "key-1",
                            "enabled": True,
                            "signature_type": "rsa-sha256",
                            "public_key_pem": self._public_key_pem,
                        }
                    ],
                }
            ]
        }
        fake_catalog = _FakeCatalogClient(
            index_payload=index_payload,
            publishers_payload=publishers_payload,
            artifact_bytes=artifact_bytes,
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router._atomic_install_or_update", return_value=AtomicResult(
            addon_dir=Path(self.tmp.name) / "addons" / "hello_world",
            backup_dir=None,
            installed_manifest={"id": "hello_world"},
        )):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world", "enable": True},
            )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["installed_release_url"], "https://example.test/beta-2.0.0.zip")

    def test_catalog_install_accepts_signature_object_schema(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-signature-object.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            use_signature_object_schema=True,
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
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
        self.assertEqual(res.json()["installed_release_url"], "https://example.test/hello_world-1.0.0.zip")

    def test_catalog_install_refreshes_source_and_retries_after_artifact_404(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-refresh-retry.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            release_url="https://example.test/stale.zip",
            fail_first_download_404=True,
            refreshed_release_url="https://example.test/fresh.zip",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
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
        self.assertEqual(res.json()["installed_release_url"], "https://example.test/fresh.zip")
        self.assertEqual(fake_catalog._refresh_calls, 1)
        self.assertEqual(fake_catalog.downloaded_urls, ["https://example.test/stale.zip", "https://example.test/fresh.zip"])

    def test_catalog_install_returns_unavailable_detail_when_artifact_404_persists_after_refresh(self) -> None:
        artifact_bytes = b"artifact-still-missing"
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            release_url="https://example.test/stale.zip",
            fail_all_download_404=True,
            refreshed_release_url="https://example.test/still-missing.zip",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router._atomic_install_or_update"):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world", "enable": True},
            )
        self.assertEqual(res.status_code, 409, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "catalog_artifact_unavailable")
        self.assertEqual(detail["source_id"], "official")
        self.assertEqual(detail["artifact_url"], "https://example.test/still-missing.zip")
        self.assertEqual(detail["retry_after_refresh"], True)
        self.assertEqual(fake_catalog._refresh_calls, 1)
        self.assertEqual(fake_catalog.downloaded_urls, ["https://example.test/stale.zip", "https://example.test/still-missing.zip"])

    def test_catalog_install_accepts_prefixed_sha256_checksum(self) -> None:
        artifact_bytes = b"artifact-prefixed-sha256"
        digest = hashlib.sha256(artifact_bytes).hexdigest()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            release_sha256=f"sha256:{digest}",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
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
        self.assertEqual(res.json()["installed_sha256"], digest)

    def test_catalog_install_sha256_mismatch_returns_detailed_payload(self) -> None:
        artifact_bytes = b"artifact-mismatch"
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            release_sha256=("0" * 64),
            release_checksum="",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
            "app.store.router._atomic_install_or_update"
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world", "enable": True},
            )
        self.assertEqual(res.status_code, 409, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "catalog_sha256_mismatch")
        self.assertEqual(detail["source_id"], "official")
        self.assertEqual(detail["expected_sha256"], [("0" * 64)])
        self.assertEqual(detail["actual_sha256"], hashlib.sha256(artifact_bytes).hexdigest())

        with patch("app.store.router._addons_root", return_value=Path(self.tmp.name) / "addons"):
            status = client.get("/api/store/status/hello_world")
        self.assertEqual(status.status_code, 200, status.text)
        status_payload = status.json()
        self.assertEqual(status_payload["installed_from_source_id"], None)
        self.assertIsNone(status_payload["installed_resolved_base_url"])
        self.assertIsNone(status_payload["installed_release_url"])
        self.assertIsNone(status_payload["installed_sha256"])
        self.assertIsNotNone(status_payload["last_install_error"])
        self.assertEqual(status_payload["last_install_error"]["error"], "catalog_sha256_mismatch")
        self.assertEqual(status_payload["last_install_error"]["source_id"], "official")
        self.assertEqual(
            status_payload["last_install_error"]["resolved_base_url"],
            "https://raw.githubusercontent.test/catalog",
        )
        self.assertEqual(
            status_payload["last_install_error"]["artifact_url"],
            "https://example.test/hello_world-1.0.0.zip",
        )
        self.assertEqual(status_payload["last_install_error"]["expected_sha256"], [("0" * 64)])
        self.assertEqual(
            status_payload["last_install_error"]["actual_sha256"],
            hashlib.sha256(artifact_bytes).hexdigest(),
        )

    def test_catalog_install_no_compatible_release_includes_reason_details(self) -> None:
        artifact_bytes = b"artifact-incompatible"
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            core_min_version="9.0.0",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router._atomic_install_or_update"):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world", "enable": True},
            )
        self.assertEqual(res.status_code, 409, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "catalog_no_compatible_release")
        self.assertEqual(detail["core_version"], "0.1.0")
        self.assertEqual(detail["reasons"][0]["error"]["code"], "core_version_too_low")
        self.assertEqual(detail["reasons"][0]["error"]["details"]["required_min"], "9.0.0")

    def test_catalog_install_missing_publisher_key_rejected(self) -> None:
        artifact_bytes = b"artifact-a"
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            publisher_key_id="missing-key",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router._atomic_install_or_update"):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world", "enable": True},
            )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"], "catalog_publisher_key_not_found_or_disabled")

    def test_catalog_install_revoked_publisher_key_rejected(self) -> None:
        artifact_bytes = b"artifact-b"
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            key_enabled=False,
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router._atomic_install_or_update"):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world", "enable": True},
            )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"], "catalog_publisher_key_not_found_or_disabled")

    def test_catalog_install_invalid_signature_rejected(self) -> None:
        artifact_bytes = b"artifact-c"
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=base64.b64encode(b"invalid").decode("utf-8"),
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router._atomic_install_or_update"):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world", "enable": True},
            )
        self.assertEqual(res.status_code, 400, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"]["code"], "signature_invalid")
        self.assertEqual(detail["error"]["details"]["source_id"], "official")
        self.assertEqual(
            detail["error"]["details"]["resolved_base_url"],
            "https://raw.githubusercontent.test/catalog",
        )
        self.assertEqual(
            detail["error"]["details"]["artifact_url"],
            "https://example.test/hello_world-1.0.0.zip",
        )
        self.assertEqual(detail["error"]["details"]["publisher_key_id"], "key-1")
        self.assertEqual(detail["error"]["details"]["signature_type"], "rsa-sha256")
        self.assertIn("release_sig must match downloaded artifact bytes", detail["error"]["details"]["hint"])

        with patch("app.store.router._addons_root", return_value=Path(self.tmp.name) / "addons"):
            status = client.get("/api/store/status/hello_world")
        self.assertEqual(status.status_code, 200, status.text)
        status_payload = status.json()
        self.assertIsNotNone(status_payload["last_install_error"])
        self.assertEqual(status_payload["last_install_error"]["error"], "signature_invalid")
        self.assertEqual(status_payload["last_install_error"]["source_id"], "official")
        self.assertEqual(
            status_payload["last_install_error"]["artifact_url"],
            "https://example.test/hello_world-1.0.0.zip",
        )
        self.assertEqual(status_payload["last_install_error"]["publisher_key_id"], "key-1")
        self.assertEqual(status_payload["last_install_error"]["signature_type"], "rsa-sha256")

    def test_catalog_install_derives_publisher_from_key_id_and_alias_publishers_schema(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-pub-alias.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            publisher_key_id="pub-1#2026-03",
            publishers_key_id="pub-1#2026-03",
            use_publishers_alias_schema=True,
            omit_publisher_id=True,
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
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

    def test_catalog_install_accepts_escaped_newline_publisher_key(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-escaped-pem.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            escape_publishers_public_key_pem=True,
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
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

    def test_catalog_install_invalid_layout_returns_structured_diagnostics(self) -> None:
        manifest_bytes = b'{"id":"hello_world","name":"hello_world","version":"1.0.0"}'
        app_main_bytes = b"from fastapi import FastAPI\napp = FastAPI()\n"
        pkg = Path(self.tmp.name) / "invalid-layout.tgz"
        with tarfile.open(pkg, "w:gz") as tf:
            manifest_info = tarfile.TarInfo(name="manifest.json")
            manifest_info.size = len(manifest_bytes)
            tf.addfile(manifest_info, BytesIO(manifest_bytes))
            app_main_info = tarfile.TarInfo(name="app/main.py")
            app_main_info.size = len(app_main_bytes)
            tf.addfile(app_main_info, BytesIO(app_main_bytes))
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            release_url="https://example.test/hello_world-1.0.0.tgz",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
            "app.store.router._addons_root", return_value=Path(self.tmp.name) / "addons"
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world", "enable": True},
            )
        self.assertEqual(res.status_code, 400, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "catalog_package_layout_invalid")
        self.assertEqual(detail["reason"], "missing_backend_entrypoint")
        self.assertEqual(detail["source_id"], "official")
        self.assertEqual(detail["resolved_base_url"], "https://raw.githubusercontent.test/catalog")
        self.assertEqual(detail["artifact_url"], "https://example.test/hello_world-1.0.0.tgz")
        self.assertEqual(detail["expected_package_profile"], "embedded_addon")
        self.assertEqual(detail["detected_package_profile"], "standalone_service")
        self.assertEqual(detail["expected_backend_entrypoint"], "backend/addon.py")
        self.assertEqual(detail["layout_hint"], "service_layout_app_main")
        self.assertIn("standalone service package", detail["hint"])

        with patch("app.store.router._addons_root", return_value=Path(self.tmp.name) / "addons"):
            status = client.get("/api/store/status/hello_world")
        self.assertEqual(status.status_code, 200, status.text)
        status_payload = status.json()
        self.assertIsNotNone(status_payload["last_install_error"])
        self.assertEqual(status_payload["last_install_error"]["error"], "catalog_package_layout_invalid")
        self.assertEqual(status_payload["last_install_error"]["source_id"], "official")
        self.assertEqual(
            status_payload["last_install_error"]["artifact_url"],
            "https://example.test/hello_world-1.0.0.tgz",
        )

    def test_catalog_install_rejects_standalone_service_profile_with_guidance(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
            "app.store.router._atomic_install_or_update"
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world", "enable": True},
            )
        self.assertEqual(res.status_code, 400, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "catalog_package_profile_unsupported")
        self.assertEqual(detail["package_profile"], "standalone_service")
        self.assertEqual(detail["supported_profiles"], ["embedded_addon"])
        self.assertEqual(detail["source_id"], "official")
        self.assertIn("deploy service package externally", detail["hint"])

    def test_catalog_install_rejects_catalog_manifest_profile_mismatch(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-profile-mismatch.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_manifest_package_profile="embedded_addon",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        with patch("app.store.router.resolve_manifest_compatibility", return_value=None), patch(
            "app.store.router._atomic_install_or_update"
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world", "enable": True},
            )
        self.assertEqual(res.status_code, 409, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "catalog_manifest_profile_mismatch")
        self.assertEqual(detail["source_id"], "official")
        self.assertEqual(detail["expected_package_profile"], "standalone_service")
        self.assertEqual(detail["detected_package_profile"], "embedded_addon")
        self.assertEqual(detail["artifact_url"], "https://example.test/hello_world-1.0.0.zip")
        self.assertIn("must match manifest package_profile", detail["hint"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
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

from app.store.router import (
    AtomicResult,
    StoreAuditLogStore,
    _artifact_temp_filename,
    _stage_standalone_artifact,
    build_store_router,
)
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
        self.registered: dict[str, dict] = {}

    def is_enabled(self, addon_id: str) -> bool:
        return self.enabled.get(addon_id, True)

    def set_enabled(self, addon_id: str, enabled: bool) -> None:
        self.enabled[addon_id] = enabled

    def delete_registered(self, addon_id: str) -> bool:
        existed = addon_id in self.registered
        if existed:
            del self.registered[addon_id]
        return existed


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
        release_version: str = "1.0.0",
        publisher_key_id: str = "key-1",
        publishers_key_id: str = "key-1",
        key_enabled: bool = True,
        signature_type: str = "rsa-sha256",
        use_addon_id_field: bool = False,
        use_publishers_alias_schema: bool = False,
        use_publishers_alias_public_key_field: bool = False,
        alias_publisher_status_value: str = "enabled",
        alias_key_status_value: str = "enabled",
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
        release_manifest_extra: dict | None = None,
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
        publisher_public_key_base64 = "".join(
            line.strip()
            for line in self._public_key_pem.splitlines()
            if line.strip() and "BEGIN PUBLIC KEY" not in line and "END PUBLIC KEY" not in line
        )
        release_payload = {
            "version": release_version,
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
        if isinstance(release_manifest_extra, dict):
            existing_manifest = release_payload.get("manifest")
            merged_manifest = dict(existing_manifest) if isinstance(existing_manifest, dict) else {}
            merged_manifest.update(release_manifest_extra)
            release_payload["manifest"] = merged_manifest
        if use_nested_artifact_url:
            release_payload["artifact"] = {"url": release_url}
        else:
            release_payload["artifact_url"] = release_url
        alias_key_payload: dict[str, object] = {
            "key_id": publishers_key_id,
            "status": alias_key_status_value if key_enabled else "revoked",
            "type": signature_type,
        }
        if use_publishers_alias_public_key_field:
            alias_key_payload["public_key"] = publisher_public_key_base64
        else:
            alias_key_payload["public_key_pem"] = publisher_public_key_pem
        publisher_record = (
            {
                "publisher_id": "pub-1",
                "status": alias_publisher_status_value,
                "keys": [alias_key_payload],
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

    def test_validate_source_reports_invalid_release_versions(self) -> None:
        artifact_bytes = b"artifact-invalid-version"
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            release_version="v1",
        )
        app = FastAPI()
        app.include_router(
            build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog),
            prefix="/api/store",
        )
        client = TestClient(app)

        res = client.get("/api/store/sources/official/validate", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["source_id"], "official")
        self.assertGreaterEqual(payload["checked_releases"], 1)
        self.assertEqual(payload["issues"][0]["code"], "catalog_release_version_invalid")

    def test_validate_source_returns_404_for_unknown_source(self) -> None:
        artifact_bytes = b"artifact-valid-version"
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
        )
        app = FastAPI()
        app.include_router(
            build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog),
            prefix="/api/store",
        )
        client = TestClient(app)

        res = client.get("/api/store/sources/missing/validate", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(res.status_code, 404, res.text)
        self.assertEqual(res.json()["detail"], "source_not_found")

    def test_catalog_endpoint_includes_publisher_display_name_from_publishers_cache(self) -> None:
        class _CatalogWithPublishers:
            def select_source(self, sources, source_id):
                for src in sources:
                    if src.id == (source_id or "official"):
                        return src
                return None

            def query_cached(self, source_id, req):
                return {
                    "ok": True,
                    "items": [
                        {
                            "id": "hello_world",
                            "name": "hello_world",
                            "publisher_id": "pub-1",
                            "releases": [],
                        }
                    ],
                    "catalog_status": {"status": "ok", "source_id": source_id},
                }

            def load_cached_documents(self, source_id):
                return (
                    {"addons": []},
                    {"publishers": [{"publisher_id": "pub-1", "display_name": "Publisher One"}]},
                )

        app = FastAPI()
        app.include_router(
            build_store_router(self.registry, self.audit, _FakeSourcesStore(), _CatalogWithPublishers()),
            prefix="/api/store",
        )
        client = TestClient(app)
        res = client.get("/api/store/catalog?source_id=official")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["items"][0]["publisher_display_name"], "Publisher One")

    def test_artifact_temp_filename_infers_tgz_suffix(self) -> None:
        filename = _artifact_temp_filename("https://example.test/releases/download/v1.0.0/addon.tgz")
        self.assertEqual(filename, "artifact.tgz")

    def test_stage_standalone_artifact_overwrites_existing_file(self) -> None:
        root = Path(self.tmp.name) / "SynthiaAddons"
        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(root)}, clear=False):
            artifact_a = b"artifact-a"
            artifact_b = b"artifact-b"
            staged = _stage_standalone_artifact("hello_world", "1.0.0", artifact_a)
            staged_second = _stage_standalone_artifact("hello_world", "1.0.0", artifact_b)
        self.assertEqual(staged, staged_second)
        self.assertEqual(staged.read_bytes(), artifact_b)

    def test_install_rejects_unknown_install_mode(self) -> None:
        res = self.client.post(
            "/api/store/install",
            headers={"X-Admin-Token": "test-token"},
            json={"addon_id": "hello_world", "source_id": "official", "install_mode": "not_real"},
        )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"], "install_mode_unsupported")

    def test_local_install_rejects_standalone_install_mode(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-local.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        res = self.client.post(
            "/api/store/install",
            headers={"X-Admin-Token": "test-token"},
            json={
                "package_path": str(pkg),
                "manifest": _manifest_payload("hello_world"),
                "public_key_pem": self._public_key_pem,
                "install_mode": "standalone_service",
            },
        )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"], "local_install_mode_unsupported")

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
        ok_payload = ok_res.json()
        self.assertEqual(ok_payload["mode"], "embedded_addon")
        self.assertIn("desired_path", ok_payload)
        self.assertIn("runtime_path", ok_payload)
        self.assertIn("staged_artifact_path", ok_payload)
        self.assertIn("runtime_state", ok_payload)
        self.assertIn("registry_state", ok_payload)

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
            self.assertIn("runtime_path", payload)
            self.assertIn("runtime_state", payload)
            self.assertIn("standalone_runtime", payload)
            self.assertEqual(payload["runtime_state"], "unknown")

        uninstall_res = self.client.post(
            "/api/store/uninstall",
            headers={"X-Admin-Token": "test-token"},
            json={"addon_id": "missing-addon"},
        )
        self.assertEqual(uninstall_res.status_code, 404, uninstall_res.text)

    def test_uninstall_removes_standalone_service_and_registry(self) -> None:
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"
        addon_dir = standalone_root / "services" / "hello_world"
        version_dir = addon_dir / "versions" / "1.0.0"
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        (addon_dir / "desired.json").write_text(
            json.dumps(
                {
                    "addon_id": "hello_world",
                    "desired_state": "running",
                    "runtime": {"project_name": "synthia-addon-hello_world"},
                }
            ),
            encoding="utf-8",
        )
        (addon_dir / "runtime.json").write_text(
            json.dumps({"addon_id": "hello_world", "active_version": "1.0.0", "state": "running"}),
            encoding="utf-8",
        )
        self.registry.registered["hello_world"] = {"id": "hello_world"}
        state_path = Path(os.environ["STORE_INSTALL_STATE_PATH"])
        state_path.write_text(
            json.dumps({"hello_world": {"installed_version": "1.0.0"}}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False), patch(
            "app.store.router.subprocess.run",
            return_value=subprocess.CompletedProcess(args=["docker", "compose"], returncode=0, stdout="", stderr=""),
        ) as down_mock:
            res = self.client.post(
                "/api/store/uninstall",
                headers={"X-Admin-Token": "test-token"},
                json={"addon_id": "hello_world"},
            )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertTrue(payload["standalone_removed"])
        self.assertFalse(payload["embedded_removed"])
        self.assertTrue(payload["registered_deleted"])
        self.assertIsNone(payload["standalone_compose_down_error"])
        down_mock.assert_called_once()
        self.assertFalse(addon_dir.exists())
        store_state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertNotIn("hello_world", store_state)

    def test_uninstall_standalone_succeeds_when_compose_down_fails(self) -> None:
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"
        addon_dir = standalone_root / "services" / "hello_world"
        version_dir = addon_dir / "versions" / "1.0.0"
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        (addon_dir / "desired.json").write_text(
            json.dumps(
                {
                    "addon_id": "hello_world",
                    "desired_state": "running",
                    "runtime": {"project_name": "synthia-addon-hello_world"},
                }
            ),
            encoding="utf-8",
        )
        (addon_dir / "runtime.json").write_text(
            json.dumps({"addon_id": "hello_world", "active_version": "1.0.0", "state": "running"}),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False), patch(
            "app.store.router.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["docker", "compose"], returncode=1, stdout="", stderr="compose failed"
            ),
        ):
            res = self.client.post(
                "/api/store/uninstall",
                headers={"X-Admin-Token": "test-token"},
                json={"addon_id": "hello_world"},
            )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertTrue(payload["standalone_removed"])
        self.assertIn("compose failed", payload["standalone_compose_down_error"])
        self.assertFalse(addon_dir.exists())

    def test_status_summary_reports_top_install_error_codes(self) -> None:
        with patch(
            "app.store.router._load_install_state",
            return_value={
                "a": {"last_install_error": {"error": "catalog_release_version_invalid"}},
                "b": {"last_install_error": {"error": "catalog_release_version_invalid"}},
                "c": {"last_install_error": {"error": "catalog_sha256_mismatch"}},
                "d": {"installed_version": "1.0.0"},
            },
        ):
            res = self.client.get("/api/store/status/summary")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["tracked_addons"], 4)
        self.assertEqual(payload["addons_with_errors"], 3)
        self.assertEqual(payload["top_errors"][0]["code"], "catalog_release_version_invalid")
        self.assertEqual(payload["top_errors"][0]["count"], 2)

    def test_status_reads_standalone_runtime_json(self) -> None:
        runtime_path = Path(self.tmp.name) / "SynthiaAddons" / "services" / "hello_world" / "runtime.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(
            json.dumps(
                {
                    "ssap_version": "1.0",
                    "addon_id": "hello_world",
                    "active_version": "1.0.0",
                    "state": "running",
                    "last_action": {"type": "start", "ok": True},
                    "health": {"status": "healthy"},
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(Path(self.tmp.name) / "SynthiaAddons")}, clear=False):
            with patch("app.store.router._addons_root", return_value=Path(self.tmp.name) / "addons"):
                res = self.client.get("/api/store/status/hello_world")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["runtime_state"], "running")
        self.assertEqual(payload["standalone_runtime"]["active_version"], "1.0.0")
        self.assertEqual(payload["standalone_runtime"]["health"]["status"], "healthy")
        self.assertFalse(payload["ui_reachable"])
        self.assertIsNone(payload["ui_redirect_target"])

    def test_status_handles_malformed_standalone_runtime_json(self) -> None:
        runtime_path = Path(self.tmp.name) / "SynthiaAddons" / "services" / "hello_world" / "runtime.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text("{not-json", encoding="utf-8")
        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(Path(self.tmp.name) / "SynthiaAddons")}, clear=False):
            with patch("app.store.router._addons_root", return_value=Path(self.tmp.name) / "addons"):
                res = self.client.get("/api/store/status/hello_world")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["runtime_state"], "unknown")
        self.assertIsNone(payload["standalone_runtime"])
        self.assertIsNotNone(payload["runtime_error"])
        self.assertFalse(payload["ui_reachable"])
        self.assertIsNone(payload["ui_redirect_target"])

    def test_status_marks_ui_reachable_when_running_with_published_ports(self) -> None:
        runtime_path = Path(self.tmp.name) / "SynthiaAddons" / "services" / "hello_world" / "runtime.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(
            json.dumps(
                {
                    "ssap_version": "1.0",
                    "addon_id": "hello_world",
                    "active_version": "1.0.0",
                    "state": "running",
                    "published_ports": ["127.0.0.1:18080->8080/tcp"],
                    "health": {"status": "healthy"},
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(Path(self.tmp.name) / "SynthiaAddons")}, clear=False):
            with patch("app.store.router._addons_root", return_value=Path(self.tmp.name) / "addons"):
                res = self.client.get("/api/store/status/hello_world")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertTrue(payload["ui_reachable"])
        self.assertEqual(payload["ui_redirect_target"], "/addons/hello_world")

    def test_status_diagnostics_returns_last_error_summary(self) -> None:
        runtime_path = Path(self.tmp.name) / "SynthiaAddons" / "services" / "hello_world" / "runtime.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(
            json.dumps(
                {
                    "ssap_version": "1.0",
                    "addon_id": "hello_world",
                    "active_version": None,
                    "state": "error",
                    "error": "compose_up_failed: failed to solve: missing Dockerfile",
                    "last_error": "compose_up_failed: failed to solve: missing Dockerfile",
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(Path(self.tmp.name) / "SynthiaAddons")}, clear=False):
            res = self.client.get("/api/store/status/hello_world/diagnostics")

        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["runtime_state"], "error")
        self.assertIn("missing Dockerfile", payload["last_error_summary"])
        self.assertEqual(
            payload["standalone_runtime"]["last_error"],
            "compose_up_failed: failed to solve: missing Dockerfile",
        )
        self.assertIn("retention", payload)

    def test_status_diagnostics_includes_retention_versions(self) -> None:
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"
        addon_dir = standalone_root / "services" / "hello_world"
        versions_dir = addon_dir / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        for idx, version in enumerate(("0.8.0", "0.9.0", "1.0.0", "1.1.0"), start=1):
            version_dir = versions_dir / version
            version_dir.mkdir(parents=True, exist_ok=True)
            ts = 1700000000 + idx
            os.utime(version_dir, (ts, ts))
        runtime_path = addon_dir / "runtime.json"
        runtime_path.write_text(
            json.dumps(
                {
                    "ssap_version": "1.0",
                    "addon_id": "hello_world",
                    "active_version": "1.1.0",
                    "previous_version": "1.0.0",
                    "state": "running",
                }
            ),
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {"SYNTHIA_ADDONS_DIR": str(standalone_root), "SYNTHIA_SUPERVISOR_KEEP_VERSIONS": "3"},
            clear=False,
        ):
            res = self.client.get("/api/store/status/hello_world/diagnostics")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        retention = payload["retention"]
        self.assertEqual(retention["keep_versions"], 3)
        self.assertEqual(retention["active_version"], "1.1.0")
        self.assertEqual(retention["previous_version"], "1.0.0")
        self.assertEqual(retention["retained_versions"], ["1.1.0", "1.0.0", "0.9.0"])
        self.assertEqual(retention["prunable_versions"], ["0.8.0"])

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
        payload = res.json()
        self.assertEqual(payload["mode"], "embedded_addon")
        self.assertIn("desired_path", payload)
        self.assertIn("runtime_path", payload)
        self.assertIn("staged_artifact_path", payload)
        self.assertIn("runtime_state", payload)
        self.assertIn("registry_state", payload)

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

    def test_catalog_install_rejects_unknown_channel_for_channels_schema(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-channels-invalid-channel.zip"
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

        with patch("app.store.router._atomic_install_or_update"):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world", "channel": "preview", "enable": True},
            )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"], "catalog_channel_not_found")

    def test_catalog_install_uses_requested_beta_channel(self) -> None:
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
                json={"source_id": "official", "addon_id": "hello_world", "channel": "beta", "enable": True},
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

    def test_catalog_install_ignores_sha256_mismatch(self) -> None:
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
        self.assertEqual(res.json()["installed_sha256"], "0" * 64)

        with patch("app.store.router._addons_root", return_value=Path(self.tmp.name) / "addons"):
            status = client.get("/api/store/status/hello_world")
        self.assertEqual(status.status_code, 200, status.text)
        status_payload = status.json()
        self.assertEqual(status_payload["installed_from_source_id"], "official")
        self.assertEqual(status_payload["installed_resolved_base_url"], "https://raw.githubusercontent.test/catalog")
        self.assertEqual(status_payload["installed_release_url"], "https://example.test/hello_world-1.0.0.zip")
        self.assertEqual(status_payload["installed_sha256"], "0" * 64)
        self.assertIsNone(status_payload["last_install_error"])

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

    def test_catalog_install_invalid_release_version_returns_remediation_payload(self) -> None:
        artifact_bytes = b"artifact-invalid-version"
        release_sig = self._sign_artifact(artifact_bytes)
        catalog_client = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=release_sig,
            release_version="v1",
        )
        app = FastAPI()
        app.include_router(
            build_store_router(
                self.registry,
                self.audit,
                sources_store=_FakeSourcesStore(),
                catalog_client=catalog_client,
            ),
            prefix="/api/store",
        )
        client = TestClient(app)
        with patch("app.store.router._atomic_install_or_update"):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={"source_id": "official", "addon_id": "hello_world"},
            )

        self.assertEqual(res.status_code, 400, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "catalog_release_version_invalid")
        self.assertEqual(detail["remediation_path"], "catalog_release_version_format")
        self.assertIn("semver", detail["hint"])

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

    def test_catalog_install_accepts_ed25519_signature_type_label(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-ed25519-label.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            signature_type="ed25519",
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

    def test_catalog_install_accepts_active_alias_status_and_public_key_field(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-active-public-key-alias.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            use_publishers_alias_schema=True,
            use_publishers_alias_public_key_field=True,
            alias_publisher_status_value="active",
            alias_key_status_value="active",
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

    def test_catalog_install_service_layout_returns_profile_layout_mismatch_guidance(self) -> None:
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
        self.assertEqual(res.status_code, 409, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "catalog_profile_layout_mismatch")
        self.assertEqual(detail["reason"], "embedded_profile_with_service_layout")
        self.assertEqual(detail["expected_package_profile"], "embedded_addon")
        self.assertEqual(detail["detected_package_profile"], "standalone_service")
        self.assertEqual(detail["source_id"], "official")
        self.assertEqual(detail["resolved_base_url"], "https://raw.githubusercontent.test/catalog")
        self.assertEqual(detail["artifact_url"], "https://example.test/hello_world-1.0.0.tgz")
        self.assertEqual(detail["layout_hint"], "service_layout_app_main")
        self.assertEqual(detail["remediation_path"], "embedded_repackage")
        self.assertEqual(detail["catalog_addon_id"], "hello_world")
        self.assertEqual(detail["catalog_release_version"], "1.0.0")
        self.assertEqual(detail["catalog_release_package_profile"], "embedded_addon")
        self.assertIn("metadata indicates embedded_addon", detail["hint"])

        with patch("app.store.router._addons_root", return_value=Path(self.tmp.name) / "addons"):
            status = client.get("/api/store/status/hello_world")
        self.assertEqual(status.status_code, 200, status.text)
        status_payload = status.json()
        self.assertIsNotNone(status_payload["last_install_error"])
        self.assertEqual(status_payload["last_install_error"]["error"], "catalog_profile_layout_mismatch")
        self.assertEqual(status_payload["last_install_error"]["source_id"], "official")
        self.assertEqual(
            status_payload["last_install_error"]["artifact_url"],
            "https://example.test/hello_world-1.0.0.tgz",
        )
        self.assertEqual(status_payload["last_install_error"]["remediation_path"], "embedded_repackage")

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
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False):
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
        self.assertEqual(detail["requested_install_mode"], "embedded_addon")
        self.assertEqual(detail["supported_profiles"], ["standalone_service"])
        self.assertEqual(detail["remediation_path"], "standalone_service_install")
        self.assertEqual(detail["source_id"], "official")
        self.assertIn("install_mode=standalone_service", detail["hint"])
        self.assertEqual(detail["mode"], "standalone_service")
        self.assertIn("desired_path", detail)
        self.assertIn("runtime_path", detail)
        self.assertIn("runtime_state", detail)
        self.assertIn("registry_state", detail)
        self.assertIn("service_dir", detail)
        staged_path = Path(detail["staged_artifact_path"])
        self.assertTrue(staged_path.exists())
        self.assertTrue(str(staged_path).endswith("services/hello_world/versions/1.0.0/addon.tgz"))
        self.assertEqual(staged_path.read_bytes(), artifact_bytes)

    def test_catalog_install_standalone_service_mode_writes_desired_and_returns_paths(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-success.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.zip",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False), patch(
            "app.store.router.resolve_manifest_compatibility", return_value=None
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "runtime_overrides": {"cpu": 1.5, "memory": "512m"},
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["mode"], "standalone_service")
        self.assertEqual(payload["requested_install_mode"], "standalone_service")
        self.assertEqual(payload["channel"], "stable")
        self.assertEqual(payload["runtime_state"], "unknown")
        self.assertIsNone(payload["active_version"])
        self.assertIsNone(payload["last_action"])
        self.assertTrue(payload["supervisor_expected"])
        self.assertIn("runtime.json not found", payload["supervisor_hint"])
        self.assertFalse(payload["ui_reachable"])
        self.assertIsNone(payload["ui_redirect_target"])
        self.assertIn("service_dir", payload)
        self.assertIn("staged_artifact_path", payload)
        self.assertTrue(Path(payload["desired_path"]).is_absolute())
        self.assertTrue(Path(payload["runtime_path"]).is_absolute())
        self.assertTrue(Path(payload["staged_artifact_path"]).is_absolute())
        self.assertTrue(Path(payload["service_dir"]).is_absolute())
        self.assertEqual(payload["security_guardrails"]["privileged"], False)
        self.assertEqual(payload["security_guardrails"]["cpu"], 1.5)
        self.assertEqual(payload["security_guardrails"]["memory"], "512m")
        self.assertEqual(payload["security_guardrails"]["service_token_env_key"], "SYNTHIA_SERVICE_TOKEN")
        self.assertTrue(Path(payload["staged_artifact_path"]).exists())
        desired_path = Path(payload["desired_path"])
        self.assertTrue(desired_path.exists())
        desired = json.loads(desired_path.read_text(encoding="utf-8"))
        self.assertEqual(desired["mode"], "standalone_service")
        self.assertEqual(desired["install_source"]["catalog_id"], "official")
        self.assertEqual(desired["install_source"]["release"]["signature"]["type"], "none")
        self.assertEqual(desired["runtime"]["project_name"], "synthia-addon-hello_world")
        self.assertEqual(desired["runtime"]["cpu"], 1.5)
        self.assertEqual(desired["runtime"]["memory"], "512m")
        self.assertFalse(desired["force_rebuild"])
        self.assertEqual(desired["enabled_docker_groups"], [])
        self.assertEqual(desired["config"]["env"]["SYNTHIA_SERVICE_TOKEN"], "${SYNTHIA_SERVICE_TOKEN}")

    def test_catalog_install_standalone_service_mode_accepts_enabled_docker_groups(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-enabled-groups.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr(
                "hello_world/manifest.json",
                json.dumps(
                    {
                        "id": "hello_world",
                        "name": "hello_world",
                        "version": "1.0.0",
                        "docker_groups": [{"name": "broker"}, {"name": "worker"}],
                    }
                ),
            )
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.zip",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False), patch(
            "app.store.router.resolve_manifest_compatibility", return_value=None
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "enabled_docker_groups": ["broker", "worker"],
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 200, res.text)
        desired = json.loads(Path(res.json()["desired_path"]).read_text(encoding="utf-8"))
        self.assertEqual(desired["enabled_docker_groups"], ["broker", "worker"])

    def test_catalog_install_standalone_service_mode_rejects_unknown_docker_groups(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-unknown-groups.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr(
                "hello_world/manifest.json",
                json.dumps({"id": "hello_world", "name": "hello_world", "version": "1.0.0", "docker_groups": [{"name": "broker"}]}),
            )
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.zip",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False), patch(
            "app.store.router.resolve_manifest_compatibility", return_value=None
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "enabled_docker_groups": ["cache"],
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"]["error"], "docker_groups_unknown")

    def test_catalog_install_standalone_service_mode_uses_manifest_runtime_default_ports(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-runtime-default-ports.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.tgz",
            release_manifest_extra={
                "runtime_defaults": {
                    "bind_localhost": False,
                    "ports": [{"host": 18081, "container": 8080, "proto": "tcp", "purpose": "http_api"}],
                }
            },
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False), patch(
            "app.store.router.resolve_manifest_compatibility", return_value=None
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        desired_path = Path(payload["desired_path"])
        desired = json.loads(desired_path.read_text(encoding="utf-8"))
        self.assertEqual(desired["runtime"]["bind_localhost"], False)
        self.assertEqual(
            desired["runtime"]["ports"],
            [{"host": 18081, "container": 8080, "proto": "tcp", "purpose": "http_api"}],
        )

    def test_catalog_install_standalone_service_mode_uses_extracted_manifest_runtime_defaults(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-runtime-defaults-from-artifact.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr(
                "hello_world/manifest.json",
                json.dumps(
                    {
                        "id": "hello_world",
                        "name": "hello_world",
                        "version": "1.0.0",
                        "runtime_defaults": {
                            "bind_localhost": False,
                            "ports": [{"host": 18080, "container": 8080, "proto": "tcp"}],
                        },
                    }
                ),
            )
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.zip",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False), patch(
            "app.store.router.resolve_manifest_compatibility", return_value=None
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        desired_path = Path(payload["desired_path"])
        desired = json.loads(desired_path.read_text(encoding="utf-8"))
        self.assertFalse(desired["runtime"]["bind_localhost"])
        self.assertEqual(
            desired["runtime"]["ports"],
            [{"host": 18080, "container": 8080, "proto": "tcp", "purpose": None}],
        )

    def test_catalog_install_standalone_service_mode_preserves_runtime_project_override(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-project-override.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.tgz",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False), patch(
            "app.store.router.resolve_manifest_compatibility", return_value=None
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "runtime_overrides": {"project_name": "custom-project"},
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        desired_path = Path(payload["desired_path"])
        desired = json.loads(desired_path.read_text(encoding="utf-8"))
        self.assertEqual(desired["runtime"]["project_name"], "custom-project")

    def test_catalog_install_standalone_service_mode_normalizes_runtime_project_override(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-project-normalize.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.tgz",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False), patch(
            "app.store.router.resolve_manifest_compatibility", return_value=None
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "runtime_overrides": {"project_name": "Synthia Addon MQTT"},
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        desired_path = Path(payload["desired_path"])
        desired = json.loads(desired_path.read_text(encoding="utf-8"))
        self.assertEqual(desired["runtime"]["project_name"], "synthia-addon-mqtt")

    def test_catalog_install_standalone_service_mode_reads_runtime_indicators(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-runtime.json.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.tgz",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"
        runtime_path = standalone_root / "services" / "hello_world" / "runtime.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(
            json.dumps({"state": "running", "active_version": "0.9.0", "last_action": "reconcile_applied"}),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False), patch(
            "app.store.router.resolve_manifest_compatibility", return_value=None
        ):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["runtime_state"], "running")
        self.assertEqual(payload["active_version"], "0.9.0")
        self.assertEqual(payload["last_action"], "reconcile_applied")
        self.assertIsNone(payload["supervisor_hint"])

    def test_standalone_update_rewrites_desired_and_sets_force_rebuild(self) -> None:
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"
        addon_dir = standalone_root / "services" / "hello_world"
        addon_dir.mkdir(parents=True, exist_ok=True)
        desired_path = addon_dir / "desired.json"
        desired_path.write_text(
            json.dumps(
                {
                    "ssap_version": "1.0",
                    "addon_id": "hello_world",
                    "mode": "standalone_service",
                    "desired_state": "running",
                    "desired_revision": "rev-old",
                    "channel": "stable",
                    "force_rebuild": False,
                    "enabled_docker_groups": [],
                    "pinned_version": "1.0.0",
                    "install_source": {
                        "type": "catalog",
                        "catalog_id": "official",
                        "release": {
                            "artifact_url": "https://example.test/hello_world-1.0.0.tgz",
                            "sha256": "",
                            "publisher_key_id": "",
                            "signature": {"type": "none", "value": ""},
                        },
                    },
                    "runtime": {
                        "orchestrator": "docker_compose",
                        "project_name": "synthia-addon-hello_world",
                        "network": "synthia_net",
                        "ports": [],
                        "bind_localhost": True,
                    },
                    "config": {"env": {"CORE_URL": "http://127.0.0.1:8000"}},
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False):
            res = self.client.post(
                "/api/store/standalone/update",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "addon_id": "hello_world",
                    "force_rebuild": True,
                    "runtime_overrides": {"ports": [{"host": 18080, "container": 8080, "proto": "tcp"}]},
                    "config_env_overrides": {"EXTRA_FLAG": "1"},
                },
            )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertTrue(payload["force_rebuild"])
        self.assertEqual(payload["enabled_docker_groups"], [])
        self.assertIsNotNone(payload["desired_revision"])
        desired = json.loads(desired_path.read_text(encoding="utf-8"))
        self.assertTrue(desired["force_rebuild"])
        self.assertNotEqual(desired["desired_revision"], "rev-old")
        self.assertEqual(desired["runtime"]["ports"], [{"host": 18080, "container": 8080, "proto": "tcp"}])
        self.assertEqual(desired["config"]["env"]["EXTRA_FLAG"], "1")

    def test_standalone_update_sets_enabled_docker_groups(self) -> None:
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"
        addon_dir = standalone_root / "services" / "hello_world"
        extracted_dir = addon_dir / "current" / "extracted"
        extracted_dir.mkdir(parents=True, exist_ok=True)
        (extracted_dir / "manifest.json").write_text(
            json.dumps(
                {"id": "hello_world", "name": "hello_world", "version": "1.0.0", "docker_groups": [{"name": "broker"}, {"name": "worker"}]}
            ),
            encoding="utf-8",
        )
        desired_path = addon_dir / "desired.json"
        desired_path.write_text(
            json.dumps(
                {
                    "ssap_version": "1.0",
                    "addon_id": "hello_world",
                    "mode": "standalone_service",
                    "desired_state": "running",
                    "desired_revision": "rev-old",
                    "channel": "stable",
                    "force_rebuild": False,
                    "enabled_docker_groups": [],
                    "pinned_version": "1.0.0",
                    "install_source": {
                        "type": "catalog",
                        "catalog_id": "official",
                        "release": {
                            "artifact_url": "https://example.test/hello_world-1.0.0.tgz",
                            "sha256": "",
                            "publisher_key_id": "",
                            "signature": {"type": "none", "value": ""},
                        },
                    },
                    "runtime": {
                        "orchestrator": "docker_compose",
                        "project_name": "synthia-addon-hello_world",
                        "network": "synthia_net",
                        "ports": [],
                        "bind_localhost": True,
                    },
                    "config": {"env": {}},
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False):
            res = self.client.post(
                "/api/store/standalone/update",
                headers={"X-Admin-Token": "test-token"},
                json={"addon_id": "hello_world", "enabled_docker_groups": ["broker", "worker"]},
            )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["enabled_docker_groups"], ["broker", "worker"])
        desired = json.loads(desired_path.read_text(encoding="utf-8"))
        self.assertEqual(desired["enabled_docker_groups"], ["broker", "worker"])

    def test_standalone_update_rejects_unknown_enabled_docker_groups(self) -> None:
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"
        addon_dir = standalone_root / "services" / "hello_world"
        extracted_dir = addon_dir / "current" / "extracted"
        extracted_dir.mkdir(parents=True, exist_ok=True)
        (extracted_dir / "manifest.json").write_text(
            json.dumps({"id": "hello_world", "name": "hello_world", "version": "1.0.0", "docker_groups": [{"name": "broker"}]}),
            encoding="utf-8",
        )
        desired_path = addon_dir / "desired.json"
        desired_path.write_text(
            json.dumps(
                {
                    "ssap_version": "1.0",
                    "addon_id": "hello_world",
                    "mode": "standalone_service",
                    "desired_state": "running",
                    "desired_revision": "rev-old",
                    "channel": "stable",
                    "force_rebuild": False,
                    "enabled_docker_groups": [],
                    "pinned_version": "1.0.0",
                    "install_source": {"type": "catalog", "catalog_id": "official", "release": {"artifact_url": "https://example.test/a.tgz"}},
                    "runtime": {
                        "orchestrator": "docker_compose",
                        "project_name": "synthia-addon-hello_world",
                        "network": "synthia_net",
                        "ports": [],
                        "bind_localhost": True,
                    },
                    "config": {"env": {}},
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False):
            res = self.client.post(
                "/api/store/standalone/update",
                headers={"X-Admin-Token": "test-token"},
                json={"addon_id": "hello_world", "enabled_docker_groups": ["cache"]},
            )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["detail"]["error"], "docker_groups_unknown")

    def test_catalog_install_standalone_service_mode_rejects_invalid_desired_state(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-invalid-desired.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.tgz",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "desired_state": "broken_state",
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("ssap_desired_invalid", res.json()["detail"])

    def test_catalog_install_standalone_service_mode_ignores_sha_mismatch(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-sha-mismatch.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.tgz",
            release_sha256="0" * 64,
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["installed_sha256"], "0" * 64)
        self.assertTrue((standalone_root / "services" / "hello_world" / "desired.json").exists())

    def test_catalog_install_standalone_service_mode_handles_artifact_404_without_desired_write(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-artifact-404.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.tgz",
            fail_all_download_404=True,
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 409, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "catalog_artifact_unavailable")
        self.assertFalse((standalone_root / "services" / "hello_world" / "desired.json").exists())

    def test_catalog_install_standalone_service_mode_rejects_host_network_override(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-host-network.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.tgz",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "runtime_overrides": {"network": "host"},
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 400, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "standalone_runtime_network_unsupported")

    def test_catalog_install_standalone_service_mode_rejects_invalid_cpu_override(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-standalone-invalid-cpu.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/app/main.py", "print('ok')\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="standalone_service",
            release_url="https://example.test/hello_world-1.0.0.tgz",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)
        standalone_root = Path(self.tmp.name) / "SynthiaAddons"

        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(standalone_root)}, clear=False):
            res = client.post(
                "/api/store/install",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "source_id": "official",
                    "addon_id": "hello_world",
                    "install_mode": "standalone_service",
                    "runtime_overrides": {"cpu": 0},
                    "enable": True,
                },
            )
        self.assertEqual(res.status_code, 400, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "standalone_runtime_cpu_invalid")

    def test_catalog_install_rejects_standalone_mode_when_release_is_embedded(self) -> None:
        pkg = Path(self.tmp.name) / "bundle-embedded-release.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("hello_world/manifest.json", '{"id":"hello_world","name":"hello_world","version":"1.0.0"}')
            zf.writestr("hello_world/backend/addon.py", "addon = None\n")
        artifact_bytes = pkg.read_bytes()
        fake_catalog = self._build_catalog_client(
            artifact_bytes=artifact_bytes,
            release_sig=self._sign_artifact(artifact_bytes),
            package_profile="embedded_addon",
        )
        app = FastAPI()
        app.include_router(build_store_router(self.registry, self.audit, _FakeSourcesStore(), fake_catalog), prefix="/api/store")
        client = TestClient(app)

        res = client.post(
            "/api/store/install",
            headers={"X-Admin-Token": "test-token"},
            json={"source_id": "official", "addon_id": "hello_world", "install_mode": "standalone_service", "enable": True},
        )
        self.assertEqual(res.status_code, 400, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "catalog_package_profile_unsupported")
        self.assertEqual(detail["package_profile"], "embedded_addon")
        self.assertEqual(detail["requested_install_mode"], "standalone_service")
        self.assertEqual(detail["remediation_path"], "embedded_addon_install")
        self.assertIn("install_mode=embedded_addon", detail["hint"])

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

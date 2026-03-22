import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    FASTAPI_STACK_AVAILABLE = True
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None
    FASTAPI_STACK_AVAILABLE = False

from app.system.platform_identity import (
    CORE_ID_PATTERN,
    DEFAULT_LEGACY_INTERNAL_NAMESPACE,
    DEFAULT_PLATFORM_ADDONS_NAME,
    DEFAULT_PLATFORM_CORE_NAME,
    DEFAULT_PLATFORM_DOCS_NAME,
    DEFAULT_PLATFORM_DOMAIN,
    DEFAULT_PLATFORM_NAME,
    DEFAULT_PLATFORM_NODES_NAME,
    DEFAULT_PLATFORM_SHORT,
    DEFAULT_PLATFORM_SUPERVISOR_NAME,
    derive_public_api_hostname,
    derive_public_ui_hostname,
    PlatformNamingService,
    default_platform_identity,
    default_platform_naming,
    is_valid_core_id,
    load_platform_identity,
    platform_identity_from_values,
)
from app.system.settings.router import build_settings_router
from app.system.settings.store import SettingsStore


class TestPlatformIdentity(unittest.TestCase):
    def test_default_platform_identity_uses_phase_one_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            identity = default_platform_identity()
        self.assertTrue(is_valid_core_id(identity.core_id))
        self.assertEqual(identity.platform_name, DEFAULT_PLATFORM_NAME)
        self.assertEqual(identity.platform_short, DEFAULT_PLATFORM_SHORT)
        self.assertEqual(identity.platform_domain, DEFAULT_PLATFORM_DOMAIN)
        self.assertEqual(identity.core_name, DEFAULT_PLATFORM_CORE_NAME)
        self.assertEqual(identity.supervisor_name, DEFAULT_PLATFORM_SUPERVISOR_NAME)
        self.assertEqual(identity.nodes_name, DEFAULT_PLATFORM_NODES_NAME)
        self.assertEqual(identity.addons_name, DEFAULT_PLATFORM_ADDONS_NAME)
        self.assertEqual(identity.docs_name, DEFAULT_PLATFORM_DOCS_NAME)
        self.assertEqual(identity.legacy_internal_namespace, DEFAULT_LEGACY_INTERNAL_NAMESPACE)
        self.assertIn(DEFAULT_LEGACY_INTERNAL_NAMESPACE, identity.legacy_compatibility_note)
        self.assertEqual(identity.public_hostname, f"{identity.core_id}.{DEFAULT_PLATFORM_DOMAIN}")
        self.assertEqual(identity.public_ui_hostname, f"{identity.core_id}.{DEFAULT_PLATFORM_DOMAIN}")
        self.assertEqual(identity.public_api_hostname, f"{identity.core_id}.{DEFAULT_PLATFORM_DOMAIN}")

    def test_platform_identity_uses_env_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SYNTHIA_CORE_ID": "0123456789abcdef",
                "PLATFORM_NAME": "Acme AI",
                "PLATFORM_SHORT": "Acme",
                "PLATFORM_DOMAIN": "acme.example",
                "PLATFORM_CORE_NAME": "Acme Control",
                "PLATFORM_SUPERVISOR_NAME": "Acme Supervisor",
                "PLATFORM_NODES_NAME": "Acme Nodes",
                "PLATFORM_ADDONS_NAME": "Acme Addons",
                "PLATFORM_DOCS_NAME": "Acme Docs",
                "PLATFORM_LEGACY_INTERNAL_NAMESPACE": "legacy",
                "PLATFORM_LEGACY_COMPATIBILITY_NOTE": "Legacy namespace remains active internally.",
            },
            clear=True,
        ):
            identity = default_platform_identity()
        self.assertEqual(identity.platform_name, "Acme AI")
        self.assertEqual(identity.core_id, "0123456789abcdef")
        self.assertEqual(identity.platform_short, "Acme")
        self.assertEqual(identity.platform_domain, "acme.example")
        self.assertEqual(identity.core_name, "Acme Control")
        self.assertEqual(identity.supervisor_name, "Acme Supervisor")
        self.assertEqual(identity.nodes_name, "Acme Nodes")
        self.assertEqual(identity.addons_name, "Acme Addons")
        self.assertEqual(identity.docs_name, "Acme Docs")
        self.assertEqual(identity.legacy_internal_namespace, "legacy")
        self.assertEqual(identity.legacy_compatibility_note, "Legacy namespace remains active internally.")
        self.assertEqual(identity.public_hostname, "0123456789abcdef.acme.example")
        self.assertEqual(identity.public_ui_hostname, "0123456789abcdef.acme.example")
        self.assertEqual(identity.public_api_hostname, "0123456789abcdef.acme.example")

    def test_platform_identity_prefers_settings_values(self) -> None:
        with patch.dict(os.environ, {"PLATFORM_NAME": "Env AI"}, clear=True):
            identity = platform_identity_from_values(
                {
                    "platform.name": "Hexe AI",
                    "platform.short": "Hexe",
                    "platform.domain": "hexe-ai.com",
                    "app.name": "Hexe Core",
                    "platform.supervisor_name": "Hexe Supervisor",
                    "platform.nodes_name": "Hexe Nodes",
                    "platform.addons_name": "Hexe Addons",
                    "platform.docs_name": "Hexe Docs",
                    "platform.legacy_compatibility_note": "Some stable technical identifiers still use `synthia` where changing them would break compatibility.",
                }
            )
        self.assertEqual(identity.platform_name, "Hexe AI")
        self.assertTrue(CORE_ID_PATTERN.fullmatch(identity.core_id))
        self.assertEqual(identity.platform_short, "Hexe")
        self.assertEqual(identity.platform_domain, "hexe-ai.com")
        self.assertEqual(identity.core_name, "Hexe Core")
        self.assertEqual(identity.supervisor_name, "Hexe Supervisor")
        self.assertEqual(identity.nodes_name, "Hexe Nodes")
        self.assertEqual(identity.addons_name, "Hexe Addons")
        self.assertEqual(identity.docs_name, "Hexe Docs")
        self.assertEqual(identity.public_hostname, f"{identity.core_id}.hexe-ai.com")
        self.assertEqual(identity.public_ui_hostname, f"{identity.core_id}.hexe-ai.com")
        self.assertEqual(identity.public_api_hostname, f"{identity.core_id}.hexe-ai.com")

    def test_hostname_derivation_rejects_invalid_core_id(self) -> None:
        self.assertFalse(is_valid_core_id("not-valid"))
        with self.assertRaises(ValueError):
            derive_public_ui_hostname("bad", "hexe-ai.com")
        with self.assertRaises(ValueError):
            derive_public_api_hostname("bad", "hexe-ai.com")


class TestPlatformNamingService(unittest.TestCase):
    def test_default_naming_service_returns_canonical_component_labels(self) -> None:
        service = default_platform_naming()
        self.assertIsInstance(service, PlatformNamingService)
        self.assertEqual(service.platform(), DEFAULT_PLATFORM_NAME)
        self.assertTrue(is_valid_core_id(service.core_id()))
        self.assertEqual(service.core(), DEFAULT_PLATFORM_CORE_NAME)
        self.assertEqual(service.supervisor(), DEFAULT_PLATFORM_SUPERVISOR_NAME)
        self.assertEqual(service.nodes(), DEFAULT_PLATFORM_NODES_NAME)
        self.assertEqual(service.addons(), DEFAULT_PLATFORM_ADDONS_NAME)
        self.assertEqual(service.docs(), DEFAULT_PLATFORM_DOCS_NAME)
        self.assertIn(DEFAULT_LEGACY_INTERNAL_NAMESPACE, service.compatibility_note())


@unittest.skipIf(not FASTAPI_STACK_AVAILABLE, "fastapi/testclient not available in this environment")
class TestPlatformIdentityApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SettingsStore(str(Path(self.tmpdir.name) / "app_settings.db"))
        app = FastAPI()
        app.include_router(build_settings_router(self.store), prefix="/api/system")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_platform_endpoint_returns_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            res = self.client.get("/api/system/platform")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["platform_name"], DEFAULT_PLATFORM_NAME)
        self.assertTrue(is_valid_core_id(payload["core_id"]))
        self.assertEqual(payload["platform_short"], DEFAULT_PLATFORM_SHORT)
        self.assertEqual(payload["platform_domain"], DEFAULT_PLATFORM_DOMAIN)
        self.assertEqual(payload["core_name"], DEFAULT_PLATFORM_CORE_NAME)
        self.assertEqual(payload["supervisor_name"], DEFAULT_PLATFORM_SUPERVISOR_NAME)
        self.assertEqual(payload["nodes_name"], DEFAULT_PLATFORM_NODES_NAME)
        self.assertEqual(payload["addons_name"], DEFAULT_PLATFORM_ADDONS_NAME)
        self.assertEqual(payload["docs_name"], DEFAULT_PLATFORM_DOCS_NAME)
        self.assertEqual(payload["legacy_internal_namespace"], DEFAULT_LEGACY_INTERNAL_NAMESPACE)
        self.assertEqual(payload["public_hostname"], f"{payload['core_id']}.{DEFAULT_PLATFORM_DOMAIN}")
        self.assertEqual(payload["public_ui_hostname"], f"{payload['core_id']}.{DEFAULT_PLATFORM_DOMAIN}")
        self.assertEqual(payload["public_api_hostname"], f"{payload['core_id']}.{DEFAULT_PLATFORM_DOMAIN}")

    def test_platform_endpoint_returns_settings_overrides(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.store._set_sync("platform.name", "Hexe AI")
            self.store._set_sync("platform.core_id", "feedfacecafebeef")
            self.store._set_sync("platform.short", "Hexe")
            self.store._set_sync("platform.domain", "hexe-ai.com")
            self.store._set_sync("app.name", "Hexe Core")
            self.store._set_sync("platform.supervisor_name", "Hexe Supervisor")
            self.store._set_sync("platform.nodes_name", "Hexe Nodes")
            self.store._set_sync("platform.addons_name", "Hexe Addons")
            self.store._set_sync("platform.docs_name", "Hexe Docs")
            res = self.client.get("/api/system/platform")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["core_id"], "feedfacecafebeef")
        self.assertEqual(payload["platform_name"], "Hexe AI")
        self.assertEqual(payload["supervisor_name"], "Hexe Supervisor")
        self.assertEqual(payload["nodes_name"], "Hexe Nodes")
        self.assertEqual(payload["addons_name"], "Hexe Addons")
        self.assertEqual(payload["docs_name"], "Hexe Docs")
        self.assertEqual(payload["public_hostname"], "feedfacecafebeef.hexe-ai.com")
        self.assertEqual(payload["public_ui_hostname"], "feedfacecafebeef.hexe-ai.com")
        self.assertEqual(payload["public_api_hostname"], "feedfacecafebeef.hexe-ai.com")


class TestLoadPlatformIdentity(unittest.IsolatedAsyncioTestCase):
    async def test_async_loader_uses_settings_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SettingsStore(str(Path(tmpdir) / "app_settings.db"))
            await store.set("platform.name", "Hexe AI")
            await store.set("platform.core_id", "1111222233334444")
            await store.set("platform.short", "Hexe")
            await store.set("platform.domain", "hexe-ai.com")
            await store.set("platform.supervisor_name", "Hexe Supervisor")
            await store.set("platform.nodes_name", "Hexe Nodes")
            await store.set("platform.addons_name", "Hexe Addons")
            await store.set("platform.docs_name", "Hexe Docs")
            identity = await load_platform_identity(store)
        self.assertEqual(identity.platform_name, "Hexe AI")
        self.assertEqual(identity.core_id, "1111222233334444")
        self.assertEqual(identity.supervisor_name, "Hexe Supervisor")
        self.assertEqual(identity.nodes_name, "Hexe Nodes")
        self.assertEqual(identity.addons_name, "Hexe Addons")
        self.assertEqual(identity.docs_name, "Hexe Docs")


if __name__ == "__main__":
    unittest.main()

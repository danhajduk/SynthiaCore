import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.addons.models import RegisteredAddon
from app.addons.proxy import build_proxy_router
from app.api.addons_registry import build_addons_registry_router


class _FakeRegistry:
    def __init__(self) -> None:
        self.registered: dict[str, RegisteredAddon] = {}

    def list_registered(self):
        return list(self.registered.values())

    async def register_remote(self, addon_id: str, *, base_url: str, name: str | None = None, version: str | None = None):
        addon = RegisteredAddon(
            id=addon_id,
            name=name or addon_id,
            version=version or "unknown",
            base_url=base_url,
        )
        self.registered[addon_id] = addon
        return addon

    async def configure_registered(self, addon_id: str, config: dict):
        raise KeyError("not_used")

    async def verify_registered(self, addon_id: str):
        raise KeyError("not_used")


class _DummyProxy:
    async def forward(self, request: Request, addon_id: str, path: str = ""):
        return JSONResponse({"ok": False, "via": "proxy", "addon_id": addon_id, "path": path}, status_code=418)


class TestAddonsProxyRoutePrecedence(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(os.environ, {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False)
        self.env_patch.start()

        self.registry = _FakeRegistry()
        app = FastAPI()
        app.include_router(build_addons_registry_router(self.registry), prefix="/api")
        app.include_router(build_proxy_router(_DummyProxy()))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env_patch.stop()

    def test_registry_register_route_wins_over_proxy(self) -> None:
        resp = self.client.post(
            "/api/addons/registry/mqtt/register",
            headers={"X-Admin-Token": "test-token"},
            json={"base_url": "http://127.0.0.1:9100", "name": "Hexe MQTT", "version": "0.1.0"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["addon"]["id"], "mqtt")


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.addons.models import RegisteredAddon
from app.api.addons_registry import build_addons_registry_router


class _FakeRegistry:
    def __init__(self) -> None:
        self.registered: dict[str, RegisteredAddon] = {
            "mqtt": RegisteredAddon(
                id="mqtt",
                name="Hexe MQTT",
                version="0.1.0",
                base_url="http://127.0.0.1:9100",
            )
        }

    def list_registered(self):
        return [self.registered["mqtt"]]

    async def register_remote(
        self,
        addon_id: str,
        *,
        base_url: str,
        name: str | None = None,
        version: str | None = None,
        ui_enabled: bool | None = None,
        ui_base_url: str | None = None,
        ui_mode: str | None = None,
    ):
        addon = RegisteredAddon(
            id=addon_id,
            name=name or addon_id,
            version=version or "unknown",
            base_url=base_url,
            ui_enabled=False if ui_enabled is None else ui_enabled,
            ui_base_url=ui_base_url,
            ui_mode=ui_mode or "server",
        )
        self.registered[addon_id] = addon
        return addon

    async def configure_registered(self, addon_id: str, config: dict):
        if addon_id not in self.registered:
            raise KeyError("addon_not_found")
        return {"applied": True, "config": config}

    async def verify_registered(self, addon_id: str):
        if addon_id not in self.registered:
            raise KeyError("addon_not_found")
        self.registered[addon_id].health_status = "ok"
        return {"status": "ok"}


class TestAddonsRegistryApi(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(
            os.environ,
            {
                "SYNTHIA_ADMIN_TOKEN": "test-token",
            },
            clear=False,
        )
        self.env_patch.start()
        self.registry = _FakeRegistry()
        app = FastAPI()
        app.include_router(build_addons_registry_router(self.registry), prefix="/api")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env_patch.stop()

    def test_list_and_get_registry(self) -> None:
        resp = self.client.get("/api/addons/registry")
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], "mqtt")
        self.assertTrue(payload[0]["ui_enabled"])
        self.assertEqual(payload[0]["ui_base_url"], "http://127.0.0.1:9100")
        self.assertEqual(payload[0]["ui_mode"], "server")

        one = self.client.get("/api/addons/registry/mqtt")
        self.assertEqual(one.status_code, 200, one.text)
        self.assertEqual(one.json()["id"], "mqtt")
        self.assertTrue(one.json()["ui_enabled"])
        self.assertEqual(one.json()["ui_base_url"], "http://127.0.0.1:9100")
        self.assertEqual(one.json()["ui_mode"], "server")

    def test_register_requires_admin(self) -> None:
        denied = self.client.post("/api/addons/registry/agent/register", json={"base_url": "http://127.0.0.1:9009"})
        self.assertEqual(denied.status_code, 401, denied.text)

        allowed = self.client.post(
            "/api/addons/registry/agent/register",
            headers={"X-Admin-Token": "test-token"},
            json={
                "base_url": "http://127.0.0.1:9009",
                "name": "Agent",
                "version": "1.2.3",
                "ui_enabled": True,
                "ui_base_url": "http://127.0.0.1:9009/ui",
                "ui_mode": "server",
            },
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(allowed.json()["addon"]["id"], "agent")
        self.assertTrue(allowed.json()["addon"]["ui_enabled"])
        self.assertEqual(allowed.json()["addon"]["ui_base_url"], "http://127.0.0.1:9009/ui")
        self.assertEqual(allowed.json()["addon"]["ui_mode"], "server")

    def test_configure_and_verify(self) -> None:
        cfg = self.client.post(
            "/api/addons/registry/mqtt/configure",
            headers={"X-Admin-Token": "test-token"},
            json={"config": {"mode": "external"}},
        )
        self.assertEqual(cfg.status_code, 200, cfg.text)
        self.assertTrue(cfg.json()["result"]["applied"])

        verify = self.client.post(
            "/api/addons/registry/mqtt/verify",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(verify.status_code, 200, verify.text)
        self.assertEqual(verify.json()["status"], "ok")

    def test_register_rejects_invalid_ui_base_url(self) -> None:
        invalid = self.client.post(
            "/api/addons/registry/agent/register",
            headers={"X-Admin-Token": "test-token"},
            json={
                "base_url": "http://127.0.0.1:9009",
                "ui_enabled": True,
                "ui_base_url": "ws://127.0.0.1:9009/ui",
            },
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)


if __name__ == "__main__":
    unittest.main()

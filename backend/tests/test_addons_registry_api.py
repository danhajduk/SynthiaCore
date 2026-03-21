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

        one = self.client.get("/api/addons/registry/mqtt")
        self.assertEqual(one.status_code, 200, one.text)
        self.assertEqual(one.json()["id"], "mqtt")

    def test_register_requires_admin(self) -> None:
        denied = self.client.post("/api/addons/registry/agent/register", json={"base_url": "http://127.0.0.1:9009"})
        self.assertEqual(denied.status_code, 401, denied.text)

        allowed = self.client.post(
            "/api/addons/registry/agent/register",
            headers={"X-Admin-Token": "test-token"},
            json={"base_url": "http://127.0.0.1:9009", "name": "Agent", "version": "1.2.3"},
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(allowed.json()["addon"]["id"], "agent")

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


if __name__ == "__main__":
    unittest.main()

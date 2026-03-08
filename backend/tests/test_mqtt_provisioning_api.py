import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.addons.models import AddonMeta, BackendAddon, RegisteredAddon
from app.addons.registry import AddonRegistry
from app.system.auth import ServiceTokenKeyStore, sign_hs256
from app.system.mqtt import MqttIntegrationStateStore, build_mqtt_router


class _FakeSettingsStore:
    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    async def get(self, key: str):
        return self._data.get(key)

    async def set(self, key: str, value):
        self._data[key] = value
        return value


class _FakeMqttManager:
    async def status(self):
        return {"ok": True}

    async def restart(self):
        return None

    async def publish_test(self, topic: str | None = None, payload: dict | None = None):
        return {"ok": True, "topic": topic or "synthia/core/mqtt/info", "payload": payload or {}}


class _FakeHttpResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {"ok": True}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class _FakeAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, headers: dict | None = None, json: dict | None = None):
        if url.endswith("/api/addon/mqtt/provision"):
            return _FakeHttpResponse(200, {"ok": True, "contract_id": "grant-1", "echo": json})
        if url.endswith("/api/addon/mqtt/revoke"):
            return _FakeHttpResponse(200, {"ok": True, "revoked": True, "echo": json})
        return _FakeHttpResponse(404, {"error": "not_found"})


class TestMqttProvisioningApi(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(os.environ, {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False)
        self.env_patch.start()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.settings = _FakeSettingsStore()
        self.key_store = ServiceTokenKeyStore(self.settings)
        self.state_store = MqttIntegrationStateStore(str(Path(self.tmpdir.name) / "mqtt_state.json"))
        self.registry = AddonRegistry(
            addons={
                "vision": BackendAddon(
                    meta=AddonMeta(id="vision", name="Vision", version="1.0.0"),
                    router=APIRouter(),
                )
            },
            errors={},
            enabled={"vision": True},
            registered={
                "mqtt": RegisteredAddon(
                    id="mqtt",
                    name="MQTT",
                    version="1.0.0",
                    base_url="http://mqtt-addon.local:9100",
                )
            },
        )
        app = FastAPI()
        app.include_router(
            build_mqtt_router(_FakeMqttManager(), self.registry, self.state_store, self.key_store),
            prefix="/api/system",
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()
        self.env_patch.stop()

    def _token(self, *, sub: str, scopes: list[str]) -> str:
        key = asyncio.run(self.key_store.active_key())
        now = int(time.time())
        return sign_hs256(
            {"alg": "HS256", "typ": "JWT", "kid": key["kid"]},
            {
                "sub": sub,
                "aud": "synthia-core",
                "scp": scopes,
                "exp": now + 600,
                "iat": now,
                "jti": f"jti-{now}",
            },
            key["secret"],
        )

    def test_provisioning_and_revocation_handshake(self) -> None:
        with patch("app.system.mqtt.approval.httpx.AsyncClient", return_value=_FakeAsyncClient()):
            approved = self.client.post(
                "/api/system/mqtt/registrations/approve",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "addon_id": "vision",
                    "access_mode": "both",
                    "publish_topics": ["synthia/addons/vision/event/#"],
                    "subscribe_topics": ["synthia/system/#"],
                    "capabilities": {"ha_discovery": "gateway_managed"},
                },
            )
            self.assertEqual(approved.status_code, 200, approved.text)
            self.assertTrue(approved.json()["ok"])

            provision = self.client.post(
                "/api/system/mqtt/registrations/vision/provision",
                headers={"X-Admin-Token": "test-token"},
            )
            self.assertEqual(provision.status_code, 200, provision.text)
            self.assertTrue(provision.json()["ok"])
            self.assertEqual(provision.json()["status"], "provisioned")

            revoked = self.client.post(
                "/api/system/mqtt/registrations/vision/revoke",
                headers={"X-Admin-Token": "test-token"},
            )
            self.assertEqual(revoked.status_code, 200, revoked.text)
            self.assertTrue(revoked.json()["ok"])
            self.assertEqual(revoked.json()["status"], "revoked")

    def test_provision_scope_checks_for_service_token(self) -> None:
        no_scope = self.client.post(
            "/api/system/mqtt/registrations/vision/provision",
            headers={"Authorization": f"Bearer {self._token(sub='vision', scopes=['mqtt.register'])}"},
        )
        self.assertEqual(no_scope.status_code, 401, no_scope.text)
        self.assertEqual(no_scope.json()["detail"], "claim_scope_missing")


if __name__ == "__main__":
    unittest.main()

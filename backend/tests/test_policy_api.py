import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.system.policy.router import build_policy_router
from app.system.policy.store import PolicyStore


class _FakeMqttManager:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []

    async def publish(self, topic: str, payload: dict, retain: bool = True, qos: int = 1):
        self.published.append({"topic": topic, "payload": payload, "retain": retain, "qos": qos})
        return {"ok": True, "topic": topic, "rc": 0}


class TestPolicyApi(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(os.environ, {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False)
        self.env_patch.start()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.grants_path = Path(self.tmpdir.name) / "policy_grants.json"
        self.revocations_path = Path(self.tmpdir.name) / "policy_revocations.json"
        self.store = PolicyStore(str(self.grants_path), str(self.revocations_path))
        self.mqtt = _FakeMqttManager()
        app = FastAPI()
        app.include_router(build_policy_router(self.store, self.mqtt), prefix="/api/policy")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.tmpdir.cleanup()

    def test_grant_upsert_uses_new_limit_fields(self) -> None:
        resp = self.client.post(
            "/api/policy/grants",
            headers={"X-Admin-Token": "test-token"},
            json={
                "grant_id": "grant-ai-1",
                "consumer_addon_id": "vision",
                "service": "ai",
                "period_start": "2026-03-01T00:00:00Z",
                "period_end": "2026-03-02T00:00:00Z",
                "limits": {
                    "max_requests": 250,
                    "max_tokens": 12000,
                    "max_cost_cents": 600,
                    "max_bytes": 4096,
                },
                "status": "active",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        grant = resp.json()["grant"]
        self.assertEqual(
            grant["limits"],
            {
                "max_requests": 250,
                "max_tokens": 12000,
                "max_cost_cents": 600,
                "max_bytes": 4096,
            },
        )
        self.assertEqual(len(self.mqtt.published), 1)
        self.assertEqual(self.mqtt.published[0]["topic"], "synthia/policy/grants/ai")
        self.assertEqual(self.mqtt.published[0]["payload"]["limits"]["max_tokens"], 12000)

        stored = json.loads(self.grants_path.read_text(encoding="utf-8"))
        self.assertEqual(stored[0]["limits"]["max_cost_cents"], 600)
        self.assertNotIn("max_units", stored[0]["limits"])
        self.assertNotIn("burst", stored[0]["limits"])

    def test_grant_upsert_accepts_legacy_limit_keys_and_normalizes(self) -> None:
        resp = self.client.post(
            "/api/policy/grants",
            headers={"X-Admin-Token": "test-token"},
            json={
                "grant_id": "grant-ai-legacy",
                "consumer_addon_id": "vision",
                "service": "ai",
                "period_start": "2026-03-01T00:00:00Z",
                "period_end": "2026-03-02T00:00:00Z",
                "limits": {"max_units": 5000, "burst": 15},
                "status": "active",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        limits = resp.json()["grant"]["limits"]
        self.assertEqual(limits["max_tokens"], 5000)
        self.assertEqual(limits["max_requests"], 15)
        self.assertNotIn("max_units", limits)
        self.assertNotIn("burst", limits)

    def test_list_grants_normalizes_existing_legacy_rows(self) -> None:
        self.grants_path.write_text(
            json.dumps(
                [
                    {
                        "grant_id": "grant-old",
                        "consumer_addon_id": "vision",
                        "service": "ai",
                        "period_start": "2026-03-01T00:00:00Z",
                        "period_end": "2026-03-02T00:00:00Z",
                        "limits": {"max_units": "777", "burst": "12"},
                        "status": "active",
                    }
                ]
            ),
            encoding="utf-8",
        )

        resp = self.client.get("/api/policy/grants")
        self.assertEqual(resp.status_code, 200, resp.text)
        grant = resp.json()["grants"][0]
        self.assertEqual(grant["limits"], {"max_requests": 12, "max_tokens": 777})

        persisted = json.loads(self.grants_path.read_text(encoding="utf-8"))[0]["limits"]
        self.assertEqual(persisted, {"max_requests": 12, "max_tokens": 777})


if __name__ == "__main__":
    unittest.main()

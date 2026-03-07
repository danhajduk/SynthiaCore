from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.system import build_system_router
from app.system.runtime import StandaloneRuntimeService


class _FakeRegistry:
    def has_addon(self, addon_id: str) -> bool:
        return addon_id == "mqtt"

    def set_enabled(self, addon_id: str, enabled: bool) -> None:
        return None

    def is_enabled(self, addon_id: str) -> bool:
        return True


class TestSystemRuntimeApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addons_root = Path(self.tmp.name) / "SynthiaAddons" / "services"
        self.addons_root.mkdir(parents=True, exist_ok=True)
        self.token_patch = patch.dict(os.environ, {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False)
        self.token_patch.start()

    def tearDown(self) -> None:
        self.token_patch.stop()
        self.tmp.cleanup()

    def _runtime_service(self) -> StandaloneRuntimeService:
        return StandaloneRuntimeService(
            cmd_runner=lambda _cmd: None,
            services_root_resolver=lambda create=False: self.addons_root,
            service_addon_dir_resolver=lambda addon_id, create=False: self.addons_root / addon_id,
        )

    def test_runtime_endpoints_require_admin_auth(self) -> None:
        app = FastAPI()
        app.include_router(build_system_router(_FakeRegistry(), self._runtime_service()), prefix="/api")
        client = TestClient(app)

        denied = client.get("/api/system/addons/runtime")
        self.assertEqual(denied.status_code, 401, denied.text)

        allowed = client.get("/api/system/addons/runtime", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(allowed.status_code, 200, allowed.text)
        payload = allowed.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["items"], [])

    def test_runtime_detail_returns_normalized_runtime(self) -> None:
        addon_dir = self.addons_root / "mqtt"
        addon_dir.mkdir(parents=True, exist_ok=True)
        (addon_dir / "desired.json").write_text(
            json.dumps(
                {
                    "ssap_version": "1.0",
                    "addon_id": "mqtt",
                    "mode": "standalone_service",
                    "desired_state": "running",
                    "runtime": {
                        "project_name": "synthia-addon-mqtt",
                        "network": "synthia_net",
                        "ports": [{"host": 1883, "container": 1883, "protocol": "tcp"}],
                    },
                    "install_source": {
                        "type": "catalog",
                        "catalog_id": "official",
                        "release": {"artifact_url": "https://example.test/mqtt.tgz"},
                    },
                    "config": {"env": {}},
                    "channel": "stable",
                }
            ),
            encoding="utf-8",
        )
        (addon_dir / "runtime.json").write_text(
            json.dumps(
                {
                    "state": "running",
                    "active_version": "1.0.0",
                    "health": {"status": "ok"},
                }
            ),
            encoding="utf-8",
        )

        app = FastAPI()
        app.include_router(build_system_router(_FakeRegistry(), self._runtime_service()), prefix="/api")
        client = TestClient(app)

        res = client.get("/api/system/addons/runtime/mqtt", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()["runtime"]
        self.assertEqual(payload["addon_id"], "mqtt")
        self.assertEqual(payload["desired_state"], "running")
        self.assertEqual(payload["runtime_state"], "running")
        self.assertEqual(payload["active_version"], "1.0.0")
        self.assertEqual(payload["health_status"], "healthy")


if __name__ == "__main__":
    unittest.main()

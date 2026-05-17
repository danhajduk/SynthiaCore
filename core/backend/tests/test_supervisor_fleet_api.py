import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.system.supervisors import SupervisorEnrollmentTokenStore, SupervisorFleetStore, build_supervisors_router


class _FakeSupervisorClient:
    def request_json(self, method: str, path: str, **_kwargs):  # noqa: ANN001
        self.requests.append((method, path))
        payloads = {
            "/api/supervisor/health": {
                "status": "ok",
                "host": {"host_id": "core-host", "hostname": "core-host"},
                "resources": {"cpu_percent_total": 10.0, "gpu_count": 0},
            },
            "/api/supervisor/runtime": {
                "host": {"host_id": "core-host", "hostname": "core-host"},
                "managed_nodes": [{"node_id": "local-node"}],
            },
            "/api/supervisor/info": {
                "supervisor_id": "local-core-supervisor",
                "host": {"host_id": "core-host", "hostname": "core-host"},
            },
            "/api/supervisor/runtimes": {"items": [{"node_id": "local-node", "node_name": "Local Node"}]},
            "/api/supervisor/core/runtimes": {"items": [{"runtime_id": "core-api", "runtime_name": "Core API"}]},
        }
        return payloads.get(path)

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []


class TestSupervisorFleetApi(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(os.environ, {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False)
        self.env_patch.start()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SupervisorFleetStore(path=Path(self.tmpdir.name) / "supervisors.json")
        self.enrollment_store = SupervisorEnrollmentTokenStore(path=Path(self.tmpdir.name) / "supervisor_enrollment_tokens.json")
        app = FastAPI()
        app.include_router(build_supervisors_router(self.store, self.enrollment_store), prefix="/api/system")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.tmpdir.cleanup()

    def test_supervisor_register_and_heartbeat_flow(self) -> None:
        headers = {"X-Admin-Token": "test-token"}
        registered = self.client.post(
            "/api/system/supervisors/register",
            headers=headers,
            json={
                "supervisor_id": "host-a",
                "supervisor_name": "Host A Supervisor",
                "host_id": "host-a",
                "hostname": "host-a.local",
                "api_base_url": "http://10.0.0.12:57665",
                "transport": "http",
                "capabilities": ["host_resources", "runtime_control"],
            },
        )
        self.assertEqual(registered.status_code, 200, registered.text)
        supervisor = registered.json()["supervisor"]
        self.assertEqual(supervisor["supervisor_id"], "host-a")
        self.assertEqual(supervisor["freshness_state"], "offline")

        heartbeat = self.client.post(
            "/api/system/supervisors/heartbeat",
            headers=headers,
            json={
                "supervisor_id": "host-a",
                "health_status": "healthy",
                "lifecycle_state": "running",
                "resources": {"cpu_percent_total": 12.5, "memory_percent": 40.0},
                "managed_node_count": 2,
                "registered_runtime_count": 3,
                "core_runtime_count": 0,
                "registered_runtimes": [
                    {
                        "node_id": "node-ai",
                        "node_name": "AI Node",
                        "node_type": "ai-node",
                        "health_status": "healthy",
                    }
                ],
                "core_runtimes": [
                    {
                        "runtime_id": "addon:mqtt",
                        "runtime_name": "Hexe MQTT",
                        "runtime_kind": "addon",
                        "health_status": "healthy",
                    }
                ],
            },
        )
        self.assertEqual(heartbeat.status_code, 200, heartbeat.text)
        updated = heartbeat.json()["supervisor"]
        self.assertEqual(updated["health_status"], "healthy")
        self.assertEqual(updated["freshness_state"], "online")
        self.assertEqual(updated["managed_node_count"], 2)
        self.assertEqual(updated["registered_runtimes"][0]["node_id"], "node-ai")
        self.assertEqual(updated["core_runtimes"][0]["runtime_id"], "addon:mqtt")

        listed = self.client.get("/api/system/supervisors", headers=headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"][0]["supervisor_id"], "host-a")
        self.assertEqual(listed.json()["items"][0]["registered_runtimes"][0]["node_name"], "AI Node")

    def test_supervisor_routes_require_admin(self) -> None:
        denied = self.client.get("/api/system/supervisors")
        self.assertEqual(denied.status_code, 401, denied.text)

    def test_supervisor_enrollment_token_exchanges_for_reporting_token(self) -> None:
        headers = {"X-Admin-Token": "test-token"}
        created = self.client.post(
            "/api/system/supervisors/enrollment-tokens",
            headers=headers,
            json={"supervisor_id": "host-b", "supervisor_name": "Host B Supervisor", "ttl_seconds": 300},
        )
        self.assertEqual(created.status_code, 200, created.text)
        enrollment_token = created.json()["enrollment_token"]
        self.assertTrue(enrollment_token.startswith("hexe_sup_enroll_"))
        self.assertNotIn(enrollment_token, (Path(self.tmpdir.name) / "supervisor_enrollment_tokens.json").read_text())

        enrolled = self.client.post(
            "/api/system/supervisors/enroll",
            json={
                "enrollment_token": enrollment_token,
                "supervisor_id": "host-b",
                "supervisor_name": "Host B Supervisor",
                "host_id": "host-b",
                "hostname": "host-b.local",
                "capabilities": ["host_resources"],
            },
        )
        self.assertEqual(enrolled.status_code, 200, enrolled.text)
        reporting_token = enrolled.json()["reporting_token"]
        self.assertTrue(reporting_token.startswith("hexe_sup_report_"))
        self.assertNotIn("reporting_token_hash", enrolled.json()["supervisor"])

        heartbeat = self.client.post(
            "/api/system/supervisors/heartbeat",
            headers={"X-Supervisor-Token": reporting_token},
            json={
                "supervisor_id": "host-b",
                "health_status": "healthy",
                "lifecycle_state": "running",
            },
        )
        self.assertEqual(heartbeat.status_code, 200, heartbeat.text)
        self.assertEqual(heartbeat.json()["supervisor"]["freshness_state"], "online")

        reused = self.client.post(
            "/api/system/supervisors/enroll",
            json={"enrollment_token": enrollment_token, "supervisor_id": "host-b"},
        )
        self.assertEqual(reused.status_code, 409, reused.text)

    def test_supervisor_reporting_token_rejects_other_supervisors(self) -> None:
        headers = {"X-Admin-Token": "test-token"}
        created = self.client.post(
            "/api/system/supervisors/enrollment-tokens",
            headers=headers,
            json={"supervisor_id": "host-c"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        enrolled = self.client.post(
            "/api/system/supervisors/enroll",
            json={"enrollment_token": created.json()["enrollment_token"], "supervisor_id": "host-c"},
        )
        self.assertEqual(enrolled.status_code, 200, enrolled.text)

        denied = self.client.post(
            "/api/system/supervisors/heartbeat",
            headers={"X-Supervisor-Token": enrolled.json()["reporting_token"]},
            json={"supervisor_id": "host-d", "health_status": "healthy"},
        )
        self.assertEqual(denied.status_code, 401, denied.text)

    def test_list_syncs_local_core_attached_supervisor(self) -> None:
        app = FastAPI()
        app.state.supervisor_client = _FakeSupervisorClient()
        app.include_router(build_supervisors_router(self.store, self.enrollment_store), prefix="/api/system")
        client = TestClient(app)

        listed = client.get("/api/system/supervisors", headers={"X-Admin-Token": "test-token"})

        self.assertEqual(listed.status_code, 200, listed.text)
        items = listed.json()["items"]
        self.assertEqual(items[0]["supervisor_id"], "local-core-supervisor")
        self.assertEqual(items[0]["transport"], "local")
        self.assertEqual(items[0]["freshness_state"], "online")
        self.assertEqual(items[0]["registered_runtime_count"], 1)
        self.assertEqual(items[0]["core_runtime_count"], 1)
        self.assertTrue(items[0]["metadata"]["attached_to_core"])


if __name__ == "__main__":
    unittest.main()

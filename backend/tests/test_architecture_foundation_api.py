from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.architecture import build_architecture_router
    from app.nodes import NodesDomainService, build_nodes_router
    from app.supervisor import SupervisorDomainService, build_supervisor_router
    from app.system.onboarding import NodeRegistrationRecord, NodeRegistrationsStore
    from app.system.runtime import StandaloneRuntimeService
    FASTAPI_STACK_AVAILABLE = True
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None
    build_architecture_router = None
    build_nodes_router = None
    build_supervisor_router = None
    NodesDomainService = None
    SupervisorDomainService = None
    NodeRegistrationRecord = None
    NodeRegistrationsStore = None
    StandaloneRuntimeService = None
    FASTAPI_STACK_AVAILABLE = False


@unittest.skipIf(not FASTAPI_STACK_AVAILABLE, "fastapi/testclient not available in this environment")
class TestArchitectureFoundationApi(unittest.TestCase):
    def test_architecture_endpoint_exposes_foundation_domains(self) -> None:
        app = FastAPI()
        app.include_router(build_architecture_router(), prefix="/api")
        client = TestClient(app)

        res = client.get("/api/architecture")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["target_architecture"], "core-supervisor-nodes")
        self.assertEqual([item["id"] for item in payload["domains"]], ["core", "supervisor", "nodes"])

    def test_supervisor_endpoints_report_runtime_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            services_root = Path(tmpdir) / "services"
            mqtt_dir = services_root / "mqtt"
            mqtt_dir.mkdir(parents=True, exist_ok=True)
            (mqtt_dir / "desired.json").write_text(
                '{"addon_id":"mqtt","desired_state":"running","runtime":{"ports":[]},"install_source":{"type":"catalog","release":{"artifact_url":"https://example.test/mqtt.tgz"}},"config":{"env":{}},"ssap_version":"1.0"}',
                encoding="utf-8",
            )
            (mqtt_dir / "runtime.json").write_text(
                '{"state":"running","active_version":"1.0.0","health":{"status":"ok"}}',
                encoding="utf-8",
            )

            runtime_service = StandaloneRuntimeService(
                cmd_runner=lambda _cmd: None,
                services_root_resolver=lambda create=False: services_root,
                service_addon_dir_resolver=lambda addon_id, create=False: services_root / addon_id,
            )
            app = FastAPI()
            app.include_router(build_supervisor_router(SupervisorDomainService(runtime_service)), prefix="/api")
            client = TestClient(app)

            health = client.get("/api/supervisor/health")
            self.assertEqual(health.status_code, 200, health.text)
            self.assertEqual(health.json()["managed_node_count"], 1)
            self.assertEqual(health.json()["healthy_node_count"], 1)
            self.assertEqual(health.json()["host"]["managed_runtime_type"], "standalone_addons")
            self.assertIn("resources", health.json())

            info = client.get("/api/supervisor/info")
            self.assertEqual(info.status_code, 200, info.text)
            self.assertEqual(info.json()["managed_nodes"][0]["node_id"], "mqtt")
            self.assertIn("boundaries", info.json())

            resources = client.get("/api/supervisor/resources")
            self.assertEqual(resources.status_code, 200, resources.text)
            self.assertIn("memory_total_bytes", resources.json())

            runtime = client.get("/api/supervisor/runtime")
            self.assertEqual(runtime.status_code, 200, runtime.text)
            self.assertEqual(runtime.json()["managed_nodes"][0]["node_id"], "mqtt")

            nodes = client.get("/api/supervisor/nodes")
            self.assertEqual(nodes.status_code, 200, nodes.text)
            self.assertEqual(nodes.json()["items"][0]["node_id"], "mqtt")
            self.assertEqual(nodes.json()["items"][0]["lifecycle_state"], "running")

    def test_nodes_endpoints_reuse_registration_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registrations = NodeRegistrationsStore(path=Path(tmpdir) / "node_registrations.json")
            started = "2026-03-16T00:00:00Z"
            registrations.upsert(
                NodeRegistrationRecord(
                    node_id="node-abc12345",
                    node_type="ai",
                    node_name="edge-node",
                    node_software_version="1.2.3",
                    requested_node_type="ai-node",
                    capabilities_summary=[],
                    trust_status="trusted",
                    source_onboarding_session_id="sess-1",
                    approved_by_user_id="admin",
                    approved_at=started,
                    created_at=started,
                    updated_at=started,
                )
            )
            app = FastAPI()
            app.include_router(build_nodes_router(NodesDomainService(registrations)), prefix="/api")
            client = TestClient(app)

            listed = client.get("/api/nodes")
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertEqual(len(listed.json()["items"]), 1)
            self.assertEqual(listed.json()["items"][0]["requested_node_type"], "ai-node")

            detail = client.get("/api/nodes/node-abc12345")
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(detail.json()["node"]["trust_status"], "trusted")


if __name__ == "__main__":
    unittest.main()

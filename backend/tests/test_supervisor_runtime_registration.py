from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.nodes import NodesDomainService, build_nodes_router
from app.supervisor import SupervisorDomainService, build_supervisor_router
from app.supervisor.runtime_store import SupervisorRuntimeNodesStore
from app.system.onboarding import NodeGovernanceStatusService, NodeGovernanceStatusStore, NodeRegistrationRecord, NodeRegistrationsStore
from app.system.runtime import StandaloneRuntimeService


class TestSupervisorRuntimeRegistration(unittest.TestCase):
    def _runtime_service(self, services_root: Path) -> StandaloneRuntimeService:
        return StandaloneRuntimeService(
            cmd_runner=lambda _cmd: None,
            services_root_resolver=lambda create=False: services_root,
            service_addon_dir_resolver=lambda addon_id, create=False: services_root / addon_id,
        )

    def test_register_and_heartbeat_real_node_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            registrations = NodeRegistrationsStore(path=root / "node_registrations.json")
            runtimes = SupervisorRuntimeNodesStore(path=root / "supervisor_runtime_nodes.json")
            governance = NodeGovernanceStatusService(NodeGovernanceStatusStore(path=root / "node_governance_status.json"))
            registrations.upsert(
                NodeRegistrationRecord(
                    node_id="node-1",
                    node_type="ai",
                    node_name="office-node",
                    node_software_version="1.0.0",
                    requested_node_type="ai-node",
                    capabilities_summary=[],
                    trust_status="trusted",
                    source_onboarding_session_id="sess-1",
                    approved_by_user_id="admin",
                    approved_at="2026-04-07T00:00:00+00:00",
                    created_at="2026-04-07T00:00:00+00:00",
                    updated_at="2026-04-07T00:00:00+00:00",
                    requested_hostname="office-node-host",
                    requested_ui_endpoint="http://office-node-host:8765/ui",
                    requested_api_base_url="http://office-node-host:8081",
                )
            )
            supervisor = SupervisorDomainService(
                self._runtime_service(root / "services"),
                runtimes,
                registrations,
            )
            nodes = NodesDomainService(registrations, governance, runtimes)

            app = FastAPI()
            app.include_router(build_supervisor_router(supervisor), prefix="/api")
            app.include_router(build_nodes_router(nodes), prefix="/api")
            client = TestClient(app)

            registered = client.post(
                "/api/supervisor/runtimes/register",
                json={
                    "node_id": "node-1",
                    "node_name": "office-node",
                    "node_type": "ai",
                    "host_id": "host-a",
                    "hostname": "host-a",
                    "runtime_state": "running",
                    "lifecycle_state": "running",
                    "health_status": "healthy",
                    "running": True,
                },
            )
            self.assertEqual(registered.status_code, 200, registered.text)
            self.assertEqual(registered.json()["node_id"], "node-1")
            self.assertEqual(registered.json()["freshness_state"], "online")

            heartbeated = client.post(
                "/api/supervisor/runtimes/heartbeat",
                json={
                    "node_id": "node-1",
                    "runtime_state": "running",
                    "lifecycle_state": "running",
                    "health_status": "healthy",
                    "resource_usage": {"cpu_percent": 12.5},
                },
            )
            self.assertEqual(heartbeated.status_code, 200, heartbeated.text)
            self.assertEqual(heartbeated.json()["resource_usage"]["cpu_percent"], 12.5)

            listed = client.get("/api/supervisor/runtimes")
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertEqual(listed.json()["items"][0]["node_id"], "node-1")

            detail = client.get("/api/supervisor/runtimes/node-1")
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(detail.json()["runtime"]["hostname"], "host-a")

            node_detail = client.get("/api/nodes/node-1")
            self.assertEqual(node_detail.status_code, 200, node_detail.text)
            self.assertEqual(node_detail.json()["node"]["runtime"]["runtime_state"], "running")
            self.assertEqual(node_detail.json()["node"]["runtime"]["host_id"], "host-a")

    def test_runtime_actions_update_desired_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtimes = SupervisorRuntimeNodesStore(path=root / "supervisor_runtime_nodes.json")
            supervisor = SupervisorDomainService(self._runtime_service(root / "services"), runtimes)
            app = FastAPI()
            app.include_router(build_supervisor_router(supervisor), prefix="/api")
            client = TestClient(app)

            created = client.post(
                "/api/supervisor/runtimes/register",
                json={
                    "node_id": "node-2",
                    "node_name": "vision-node",
                    "node_type": "vision",
                },
            )
            self.assertEqual(created.status_code, 200, created.text)

            restarted = client.post("/api/supervisor/runtimes/node-2/restart")
            self.assertEqual(restarted.status_code, 200, restarted.text)
            self.assertEqual(restarted.json()["action"], "restart")
            self.assertEqual(restarted.json()["runtime"]["lifecycle_state"], "restarting")

            stopped = client.post("/api/supervisor/runtimes/node-2/stop")
            self.assertEqual(stopped.status_code, 200, stopped.text)
            self.assertEqual(stopped.json()["runtime"]["desired_state"], "stopped")

    def test_heartbeat_for_unknown_runtime_returns_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtimes = SupervisorRuntimeNodesStore(path=root / "supervisor_runtime_nodes.json")
            supervisor = SupervisorDomainService(self._runtime_service(root / "services"), runtimes)
            app = FastAPI()
            app.include_router(build_supervisor_router(supervisor), prefix="/api")
            client = TestClient(app)

            missing = client.post(
                "/api/supervisor/runtimes/heartbeat",
                json={"node_id": "missing-node", "runtime_state": "running"},
            )
            self.assertEqual(missing.status_code, 404, missing.text)

    def test_register_and_manage_core_runtimes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtimes = SupervisorRuntimeNodesStore(path=root / "supervisor_runtime_nodes.json")
            supervisor = SupervisorDomainService(self._runtime_service(root / "services"), runtimes)
            app = FastAPI()
            app.include_router(build_supervisor_router(supervisor), prefix="/api")
            client = TestClient(app)

            core_created = client.post(
                "/api/supervisor/core/runtimes/register",
                json={
                    "runtime_id": "core-api",
                    "runtime_name": "Hexe Core API",
                    "runtime_kind": "core_service",
                    "management_mode": "manage",
                },
            )
            self.assertEqual(core_created.status_code, 200, core_created.text)
            self.assertEqual(core_created.json()["management_mode"], "monitor")

            core_action = client.post("/api/supervisor/core/runtimes/core-api/restart")
            self.assertEqual(core_action.status_code, 409, core_action.text)
            self.assertEqual(core_action.json()["detail"], "core_runtime_monitor_only")

            addon_created = client.post(
                "/api/supervisor/core/runtimes/register",
                json={
                    "runtime_id": "addon:voice",
                    "runtime_name": "Voice Addon",
                    "runtime_kind": "addon",
                    "management_mode": "manage",
                },
            )
            self.assertEqual(addon_created.status_code, 200, addon_created.text)

            stopped = client.post("/api/supervisor/core/runtimes/addon:voice/stop")
            self.assertEqual(stopped.status_code, 200, stopped.text)
            self.assertEqual(stopped.json()["runtime"]["desired_state"], "stopped")


if __name__ == "__main__":
    unittest.main()

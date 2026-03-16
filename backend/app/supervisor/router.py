from __future__ import annotations

from fastapi import APIRouter

from .models import (
    HostResourceSummary,
    ManagedNodeSummary,
    SupervisorHealthSummary,
    SupervisorInfoSummary,
    SupervisorNodeActionResult,
    SupervisorRuntimeSummary,
)
from .service import SupervisorDomainService


def build_supervisor_router(service: SupervisorDomainService | None = None) -> APIRouter:
    router = APIRouter(tags=["supervisor"])
    supervisor = service or SupervisorDomainService()

    @router.get("/supervisor/health")
    def get_supervisor_health() -> SupervisorHealthSummary:
        return supervisor.health_summary()

    @router.get("/supervisor/info")
    def get_supervisor_info() -> SupervisorInfoSummary:
        return supervisor.info_summary()

    @router.get("/supervisor/resources")
    def get_supervisor_resources() -> HostResourceSummary:
        return supervisor.resources_summary()

    @router.get("/supervisor/runtime")
    def get_supervisor_runtime() -> SupervisorRuntimeSummary:
        return supervisor.runtime_summary()

    @router.get("/supervisor/nodes")
    def list_supervisor_nodes() -> dict[str, list[ManagedNodeSummary]]:
        return {"items": supervisor.list_managed_nodes()}

    @router.post("/supervisor/nodes/{node_id}/start")
    def start_supervisor_node(node_id: str) -> SupervisorNodeActionResult:
        return supervisor.start_managed_node(node_id)

    @router.post("/supervisor/nodes/{node_id}/stop")
    def stop_supervisor_node(node_id: str) -> SupervisorNodeActionResult:
        return supervisor.stop_managed_node(node_id)

    @router.post("/supervisor/nodes/{node_id}/restart")
    def restart_supervisor_node(node_id: str) -> SupervisorNodeActionResult:
        return supervisor.restart_managed_node(node_id)

    return router

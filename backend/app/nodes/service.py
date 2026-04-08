from __future__ import annotations

from fastapi import HTTPException

from app.system.onboarding import NodeGovernanceStatusService, NodeRegistrationsStore
from app.supervisor.runtime_store import SupervisorRuntimeNodesStore

from .models import NodeRecord
from .registry import NodeRegistry


class NodesDomainService:
    def __init__(
        self,
        registrations_store: NodeRegistrationsStore | None = None,
        node_governance_status_service: NodeGovernanceStatusService | None = None,
        runtime_store: SupervisorRuntimeNodesStore | None = None,
    ) -> None:
        self._registry = NodeRegistry(
            registrations_store=registrations_store or NodeRegistrationsStore(),
            node_governance_status_service=node_governance_status_service,
            runtime_store=runtime_store,
        )

    def list_nodes(self) -> list[NodeRecord]:
        return self._registry.list()

    def get_node(self, node_id: str) -> NodeRecord:
        item = self._registry.get(node_id)
        if item is None:
            raise HTTPException(status_code=404, detail="node_not_found")
        return item

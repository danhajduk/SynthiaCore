from __future__ import annotations

from app.system.onboarding import NodeGovernanceStatusService, NodeRegistrationsStore, node_registry_payload
from app.supervisor.runtime_store import SupervisorRuntimeNodesStore

from .models import (
    NodeCapabilityActivationSummary,
    NodeCapabilityCategorySummary,
    NodeCapabilitySummary,
    NodeCapabilityTaxonomySummary,
    NodeRecord,
    NodeRuntimeSummary,
    NodeStatusSummary,
)


def _node_record_from_payload(payload: dict[str, object]) -> NodeRecord:
    taxonomy_payload = payload.get("capability_taxonomy") if isinstance(payload.get("capability_taxonomy"), dict) else {}
    taxonomy_categories = taxonomy_payload.get("categories") if isinstance(taxonomy_payload.get("categories"), list) else []
    activation_payload = taxonomy_payload.get("activation") if isinstance(taxonomy_payload.get("activation"), dict) else {}
    return NodeRecord(
        node_id=str(payload.get("node_id") or ""),
        node_name=str(payload.get("node_name") or ""),
        node_type=str(payload.get("node_type") or ""),
        requested_node_type=str(payload.get("requested_node_type") or "").strip() or None,
        requested_hostname=str(payload.get("requested_hostname") or "").strip() or None,
        requested_ui_endpoint=str(payload.get("requested_ui_endpoint") or "").strip() or None,
        requested_api_base_url=str(payload.get("requested_api_base_url") or "").strip() or None,
        ui_enabled=bool(payload.get("ui_enabled")),
        ui_base_url=str(payload.get("ui_base_url") or "").strip() or None,
        ui_mode=str(payload.get("ui_mode") or "").strip() or "spa",
        ui_health_endpoint=str(payload.get("ui_health_endpoint") or "").strip() or None,
        api_base_url=str(payload.get("api_base_url") or "").strip() or None,
        node_software_version=str(payload.get("node_software_version") or ""),
        approved_by_user_id=str(payload.get("approved_by_user_id") or "").strip() or None,
        approved_at=str(payload.get("approved_at") or "").strip() or None,
        source_onboarding_session_id=str(payload.get("source_onboarding_session_id") or "").strip() or None,
        created_at=str(payload.get("created_at") or "").strip() or None,
        updated_at=str(payload.get("updated_at") or "").strip() or None,
        provider_intelligence=[
            dict(item) for item in list(payload.get("provider_intelligence") or []) if isinstance(item, dict)
        ],
        capabilities=NodeCapabilitySummary(
            declared_capabilities=[str(v) for v in list(payload.get("declared_capabilities") or []) if str(v).strip()],
            enabled_providers=[str(v) for v in list(payload.get("enabled_providers") or []) if str(v).strip()],
            capability_profile_id=str(payload.get("capability_profile_id") or "").strip() or None,
            capability_status=str(payload.get("capability_status") or "missing"),
            capability_declaration_version=str(payload.get("capability_declaration_version") or "").strip() or None,
            capability_declaration_timestamp=str(payload.get("capability_declaration_timestamp") or "").strip() or None,
            taxonomy=NodeCapabilityTaxonomySummary(
                version=str(taxonomy_payload.get("version") or "1"),
                categories=[
                    NodeCapabilityCategorySummary(
                        category_id=str(item.get("category_id") or ""),
                        label=str(item.get("label") or ""),
                        items=[str(v) for v in list(item.get("items") or []) if str(v).strip()],
                        item_count=int(item.get("item_count") or 0),
                    )
                    for item in taxonomy_categories
                    if isinstance(item, dict)
                ],
                activation=NodeCapabilityActivationSummary(
                    stage=str(activation_payload.get("stage") or "not_declared"),
                    declaration_received=bool(activation_payload.get("declaration_received")),
                    profile_accepted=bool(activation_payload.get("profile_accepted")),
                    governance_issued=bool(activation_payload.get("governance_issued")),
                    operational=bool(activation_payload.get("operational")),
                ),
            ),
        ),
        status=NodeStatusSummary(
            trust_status=str(payload.get("trust_status") or "pending"),
            registry_state=str(payload.get("registry_state") or "pending"),
            governance_sync_status=str(payload.get("governance_sync_status") or "pending"),
            operational_ready=bool(payload.get("operational_ready")),
            active_governance_version=str(payload.get("active_governance_version") or "").strip() or None,
            governance_last_issued_at=str(payload.get("governance_last_issued_at") or "").strip() or None,
            governance_last_refresh_request_at=str(payload.get("governance_last_refresh_request_at") or "").strip() or None,
            governance_freshness_state=str(payload.get("governance_freshness_state") or "pending"),
            governance_freshness_changed_at=str(payload.get("governance_freshness_changed_at") or "").strip() or None,
            governance_stale_for_s=(
                int(payload.get("governance_stale_for_s"))
                if payload.get("governance_stale_for_s") is not None
                else None
            ),
            governance_outdated=bool(payload.get("governance_outdated")),
        ),
    )


def _runtime_summary_from_store(runtime_store: SupervisorRuntimeNodesStore | None, node_id: str) -> NodeRuntimeSummary | None:
    if runtime_store is None:
        return None
    runtime = runtime_store.get(node_id)
    if runtime is None:
        return None
    return NodeRuntimeSummary(
        desired_state=runtime.desired_state,
        runtime_state=runtime.runtime_state,
        lifecycle_state=runtime.lifecycle_state,
        health_status=runtime.health_status,
        freshness_state=runtime.freshness_state,
        host_id=runtime.host_id,
        hostname=runtime.hostname,
        api_base_url=runtime.api_base_url,
        ui_base_url=runtime.ui_base_url,
        last_seen_at=runtime.last_seen_at,
        last_action=runtime.last_action,
        last_action_at=runtime.last_action_at,
        last_error=runtime.last_error,
        running=runtime.running,
        resource_usage=dict(runtime.resource_usage or {}),
        runtime_metadata=dict(runtime.runtime_metadata or {}),
    )


class NodeRegistry:
    def __init__(
        self,
        registrations_store: NodeRegistrationsStore | None = None,
        node_governance_status_service: NodeGovernanceStatusService | None = None,
        runtime_store: SupervisorRuntimeNodesStore | None = None,
    ) -> None:
        self._registrations_store = registrations_store or NodeRegistrationsStore()
        self._node_governance_status_service = node_governance_status_service
        self._runtime_store = runtime_store

    def list(self) -> list[NodeRecord]:
        items: list[NodeRecord] = []
        for item in self._registrations_store.list():
            record = _node_record_from_payload(node_registry_payload(item, self._node_governance_status_service))
            record.runtime = _runtime_summary_from_store(self._runtime_store, record.node_id)
            items.append(record)
        return items

    def get(self, node_id: str) -> NodeRecord | None:
        item = self._registrations_store.get(node_id)
        if item is None:
            return None
        record = _node_record_from_payload(node_registry_payload(item, self._node_governance_status_service))
        record.runtime = _runtime_summary_from_store(self._runtime_store, record.node_id)
        return record

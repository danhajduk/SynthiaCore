from __future__ import annotations

from app.system.onboarding import NodeRegistrationsStore

from .runtime_store import SupervisorRuntimeNodeRecord, SupervisorRuntimeNodesStore


def merge_runtime_identity(
    record: SupervisorRuntimeNodeRecord,
    registrations_store: NodeRegistrationsStore | None = None,
) -> SupervisorRuntimeNodeRecord:
    if registrations_store is None:
        return record
    registration = registrations_store.get(record.node_id)
    if registration is None:
        return record
    merged = SupervisorRuntimeNodeRecord(
        node_id=record.node_id,
        node_name=record.node_name or registration.node_name,
        node_type=record.node_type or registration.node_type,
        desired_state=record.desired_state,
        runtime_state=record.runtime_state,
        lifecycle_state=record.lifecycle_state,
        health_status=record.health_status,
        registered_at=record.registered_at,
        updated_at=record.updated_at,
        host_id=record.host_id,
        hostname=record.hostname or registration.requested_hostname,
        api_base_url=record.api_base_url or registration.api_base_url,
        ui_base_url=record.ui_base_url or registration.ui_base_url,
        health_detail=record.health_detail,
        freshness_state=record.freshness_state,
        last_seen_at=record.last_seen_at,
        last_action=record.last_action,
        last_action_at=record.last_action_at,
        last_error=record.last_error,
        running=record.running,
        runtime_metadata=dict(record.runtime_metadata or {}),
        resource_usage=dict(record.resource_usage or {}),
        schema_version=record.schema_version,
    )
    return merged

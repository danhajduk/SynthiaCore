from __future__ import annotations

from .capability_taxonomy import capability_taxonomy_payload
from .governance_status import NodeGovernanceStatusService


def registry_state_from_trust_status(value: str | None) -> str:
    status = str(value or "").strip().lower()
    if status in {"trusted", "approved", "pending", "revoked"}:
        return status
    if status == "rejected":
        return "revoked"
    return "pending"


def node_capability_status(item) -> str:
    profile_id = str(getattr(item, "capability_profile_id", "") or "").strip()
    declared_at = str(getattr(item, "capability_declaration_timestamp", "") or "").strip()
    if profile_id:
        return "accepted"
    if declared_at:
        return "declared"
    return "missing"


def node_registry_payload(item, node_governance_status_service: NodeGovernanceStatusService | None = None) -> dict[str, object]:
    trust_status = str(getattr(item, "trust_status", "") or "").strip().lower()
    capability_status = node_capability_status(item)
    governance_status = "pending"
    active_governance_version = None
    governance_last_issued_at = None
    governance_last_refresh_request_at = None
    governance_freshness_state = "pending"
    governance_freshness_changed_at = None
    governance_stale_for_s = None
    governance_outdated = False
    if node_governance_status_service is not None:
        status = node_governance_status_service.get_status(str(getattr(item, "node_id", "") or ""))
        if status is not None:
            active_governance_version = status.active_governance_version
            governance_last_issued_at = status.last_issued_timestamp
            governance_last_refresh_request_at = status.last_refresh_request_timestamp
            if str(status.active_governance_version or "").strip():
                governance_status = "issued"
            freshness = node_governance_status_service.governance_freshness(str(getattr(item, "node_id", "") or ""))
            governance_freshness_state = str(freshness.get("state") or "pending")
            governance_freshness_changed_at = str(
                freshness.get("changed_at") or getattr(status, "freshness_changed_at", "") or ""
            ).strip() or None
            governance_stale_for_s = freshness.get("stale_for_s")
            governance_outdated = bool(freshness.get("outdated"))
    if capability_status == "missing":
        governance_status = "pending_capability"
    operational_ready = bool(trust_status == "trusted" and capability_status == "accepted" and governance_status == "issued")
    capability_taxonomy = capability_taxonomy_payload(
        declared_task_families=list(getattr(item, "declared_capabilities", []) or []),
        enabled_providers=list(getattr(item, "enabled_providers", []) or []),
        provider_intelligence=[dict(v) for v in list(getattr(item, "provider_intelligence", []) or []) if isinstance(v, dict)],
        capability_status=capability_status,
        governance_sync_status=governance_status,
        operational_ready=operational_ready,
    )
    return {
        "node_id": getattr(item, "node_id", None),
        "node_name": getattr(item, "node_name", None),
        "node_type": getattr(item, "node_type", None),
        "node_software_version": getattr(item, "node_software_version", None),
        "requested_node_name": getattr(item, "node_name", None),
        "requested_node_type": getattr(item, "requested_node_type", None) or getattr(item, "node_type", None),
        "requested_node_software_version": getattr(item, "node_software_version", None),
        "requested_hostname": getattr(item, "requested_hostname", None),
        "requested_ui_endpoint": getattr(item, "requested_ui_endpoint", None),
        "trust_status": trust_status or "pending",
        "registry_state": registry_state_from_trust_status(trust_status),
        "approved_by_user_id": getattr(item, "approved_by_user_id", None),
        "approved_at": getattr(item, "approved_at", None),
        "declared_capabilities": list(getattr(item, "declared_capabilities", []) or []),
        "enabled_providers": list(getattr(item, "enabled_providers", []) or []),
        "provider_intelligence": [dict(v) for v in list(getattr(item, "provider_intelligence", []) or []) if isinstance(v, dict)],
        "capability_declaration_version": getattr(item, "capability_declaration_version", None),
        "capability_declaration_timestamp": getattr(item, "capability_declaration_timestamp", None),
        "capability_profile_id": getattr(item, "capability_profile_id", None),
        "capability_status": capability_status,
        "capability_taxonomy": capability_taxonomy,
        "governance_sync_status": governance_status,
        "operational_ready": operational_ready,
        "active_governance_version": active_governance_version,
        "governance_last_issued_at": governance_last_issued_at,
        "governance_last_refresh_request_at": governance_last_refresh_request_at,
        "governance_freshness_state": governance_freshness_state,
        "governance_freshness_changed_at": governance_freshness_changed_at,
        "governance_stale_for_s": governance_stale_for_s,
        "governance_outdated": governance_outdated,
        "source_onboarding_session_id": getattr(item, "source_onboarding_session_id", None),
        "created_at": getattr(item, "created_at", None),
        "updated_at": getattr(item, "updated_at", None),
    }

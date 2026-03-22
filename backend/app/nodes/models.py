from __future__ import annotations

from pydantic import BaseModel, Field


class NodeCapabilityCategorySummary(BaseModel):
    category_id: str
    label: str
    items: list[str] = Field(default_factory=list)
    item_count: int = 0


class NodeCapabilityActivationSummary(BaseModel):
    stage: str = "not_declared"
    declaration_received: bool = False
    profile_accepted: bool = False
    governance_issued: bool = False
    operational: bool = False


class NodeCapabilityTaxonomySummary(BaseModel):
    version: str = "1"
    categories: list[NodeCapabilityCategorySummary] = Field(default_factory=list)
    activation: NodeCapabilityActivationSummary = Field(default_factory=NodeCapabilityActivationSummary)


class NodeCapabilitySummary(BaseModel):
    declared_capabilities: list[str] = Field(default_factory=list)
    enabled_providers: list[str] = Field(default_factory=list)
    capability_profile_id: str | None = None
    capability_status: str = "missing"
    capability_declaration_version: str | None = None
    capability_declaration_timestamp: str | None = None
    taxonomy: NodeCapabilityTaxonomySummary = Field(default_factory=NodeCapabilityTaxonomySummary)


class NodeStatusSummary(BaseModel):
    trust_status: str = "pending"
    registry_state: str = "pending"
    governance_sync_status: str = "pending"
    operational_ready: bool = False
    active_governance_version: str | None = None
    governance_last_issued_at: str | None = None
    governance_last_refresh_request_at: str | None = None
    governance_freshness_state: str = "pending"
    governance_freshness_changed_at: str | None = None
    governance_stale_for_s: int | None = None
    governance_outdated: bool = False


class NodeRecord(BaseModel):
    node_id: str
    node_name: str
    node_type: str
    requested_node_type: str | None = None
    requested_hostname: str | None = None
    requested_ui_endpoint: str | None = None
    node_software_version: str
    approved_by_user_id: str | None = None
    approved_at: str | None = None
    source_onboarding_session_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    provider_intelligence: list[dict[str, object]] = Field(default_factory=list)
    capabilities: NodeCapabilitySummary = Field(default_factory=NodeCapabilitySummary)
    status: NodeStatusSummary = Field(default_factory=NodeStatusSummary)


class NodeRegistryListResponse(BaseModel):
    items: list[NodeRecord] = Field(default_factory=list)

from __future__ import annotations

from pydantic import BaseModel, Field


class HostIdentitySummary(BaseModel):
    host_id: str
    hostname: str
    runtime_provider: str
    managed_runtime_type: str = "standalone_addons"


class HostResourceSummary(BaseModel):
    uptime_s: float = Field(ge=0)
    load_1m: float = Field(ge=0)
    load_5m: float = Field(ge=0)
    load_15m: float = Field(ge=0)
    cpu_percent_total: float = Field(ge=0, le=100)
    cpu_cores_logical: int = Field(ge=0)
    memory_total_bytes: int = Field(ge=0)
    memory_available_bytes: int = Field(ge=0)
    memory_percent: float = Field(ge=0, le=100)
    root_disk_total_bytes: int | None = Field(default=None, ge=0)
    root_disk_free_bytes: int | None = Field(default=None, ge=0)
    root_disk_percent: float | None = Field(default=None, ge=0, le=100)


class ManagedNodeSummary(BaseModel):
    node_id: str
    runtime_kind: str = "standalone_addon"
    lifecycle_state: str = "unknown"
    desired_state: str
    runtime_state: str
    health_status: str
    active_version: str | None = None
    running: bool | None = None
    last_action: str | None = None
    last_action_at: str | None = None


class SupervisorRegisteredRuntimeSummary(BaseModel):
    node_id: str
    node_name: str
    node_type: str
    runtime_kind: str = "real_node"
    desired_state: str
    runtime_state: str
    lifecycle_state: str
    health_status: str
    freshness_state: str = "unknown"
    host_id: str | None = None
    hostname: str | None = None
    api_base_url: str | None = None
    ui_base_url: str | None = None
    health_detail: str | None = None
    registered_at: str | None = None
    updated_at: str | None = None
    last_seen_at: str | None = None
    last_action: str | None = None
    last_action_at: str | None = None
    last_error: str | None = None
    running: bool | None = None
    resource_usage: dict[str, object] = Field(default_factory=dict)
    runtime_metadata: dict[str, object] = Field(default_factory=dict)


class SupervisorRuntimeRegistrationRequest(BaseModel):
    node_id: str
    node_name: str
    node_type: str
    host_id: str | None = None
    hostname: str | None = None
    api_base_url: str | None = None
    ui_base_url: str | None = None
    desired_state: str = "running"
    runtime_state: str = "running"
    lifecycle_state: str = "running"
    health_status: str = "unknown"
    health_detail: str | None = None
    last_error: str | None = None
    running: bool | None = True
    resource_usage: dict[str, object] = Field(default_factory=dict)
    runtime_metadata: dict[str, object] = Field(default_factory=dict)


class SupervisorRuntimeHeartbeatRequest(BaseModel):
    node_id: str
    host_id: str | None = None
    hostname: str | None = None
    api_base_url: str | None = None
    ui_base_url: str | None = None
    runtime_state: str | None = None
    lifecycle_state: str | None = None
    health_status: str | None = None
    health_detail: str | None = None
    last_error: str | None = None
    running: bool | None = None
    resource_usage: dict[str, object] = Field(default_factory=dict)
    runtime_metadata: dict[str, object] = Field(default_factory=dict)


class SupervisorRuntimeActionResult(BaseModel):
    action: str
    runtime: SupervisorRegisteredRuntimeSummary


class ProcessResourceSummary(BaseModel):
    rss_bytes: int | None = Field(default=None, ge=0)
    cpu_percent: float | None = Field(default=None)
    open_fds: int | None = Field(default=None, ge=0)
    threads: int | None = Field(default=None, ge=0)


class SupervisorOwnershipBoundary(BaseModel):
    owns: list[str] = Field(default_factory=list)
    depends_on_core_for: list[str] = Field(default_factory=list)


class SupervisorHealthSummary(BaseModel):
    status: str
    host: HostIdentitySummary
    resources: HostResourceSummary
    managed_node_count: int = Field(ge=0)
    healthy_node_count: int = Field(ge=0)
    unhealthy_node_count: int = Field(ge=0)


class SupervisorInfoSummary(BaseModel):
    supervisor_id: str
    host: HostIdentitySummary
    resources: HostResourceSummary
    boundaries: SupervisorOwnershipBoundary
    managed_node_count: int = Field(ge=0)
    managed_nodes: list[ManagedNodeSummary] = Field(default_factory=list)


class SupervisorRuntimeSummary(BaseModel):
    host: HostIdentitySummary
    resources: HostResourceSummary
    process: ProcessResourceSummary
    managed_node_count: int = Field(ge=0)
    managed_nodes: list[ManagedNodeSummary] = Field(default_factory=list)


class SupervisorAdmissionContextSummary(BaseModel):
    admission_state: str = "unknown"
    execution_host_ready: bool = False
    unavailable_reason: str | None = None
    host_busy_rating: int = Field(ge=0, le=10)
    total_capacity_units: int = Field(ge=0)
    available_capacity_units: int = Field(ge=0)
    managed_node_count: int = Field(ge=0)
    healthy_managed_node_count: int = Field(ge=0)


class SupervisorNodeActionResult(BaseModel):
    action: str
    node: ManagedNodeSummary

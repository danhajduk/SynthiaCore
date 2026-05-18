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
    gpu_count: int = Field(default=0, ge=0)
    gpu_utilization_percent: float | None = Field(default=None, ge=0, le=100)
    gpu_memory_percent: float | None = Field(default=None, ge=0, le=100)
    gpu_devices: list[dict[str, object]] = Field(default_factory=list)
    cuda_available: bool = False
    cuda_version: str | None = None
    bluetooth_present: bool = False
    bluetooth_powered: bool = False
    bluetooth_ensure_powered: bool = False
    bluetooth_power_error: str | None = None
    bluetooth_adapters: list[dict[str, object]] = Field(default_factory=list)
    network_rx_Bps: float | None = Field(default=None, ge=0)
    network_tx_Bps: float | None = Field(default=None, ge=0)
    network_bytes_recv: int | None = Field(default=None, ge=0)
    network_bytes_sent: int | None = Field(default=None, ge=0)
    network_errin: int | None = Field(default=None, ge=0)
    network_errout: int | None = Field(default=None, ge=0)
    network_dropin: int | None = Field(default=None, ge=0)
    network_dropout: int | None = Field(default=None, ge=0)
    network_primary_interface: str | None = None
    network_primary_type: str = "unknown"
    network_link_speed_mbps: int | None = Field(default=None, ge=0)
    wifi_signal_percent: float | None = Field(default=None, ge=0, le=100)


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


class SupervisorNodeServiceSummary(BaseModel):
    service_id: str
    service_state: str
    service_name: str | None = None
    desired_state: str | None = None
    health_status: str | None = None
    updated_at: str | None = None
    pid: int | None = Field(default=None, ge=0)
    container_name: str | None = None
    container_id: str | None = None
    cpu_percent: float | None = Field(default=None)
    mem_percent: float | None = Field(default=None)
    rss_bytes: int | None = Field(default=None, ge=0)
    resource_source: str | None = None
    sampled_at: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class SupervisorNodeServicesSummary(BaseModel):
    node_id: str
    api_base_url: str | None = None
    services: list[SupervisorNodeServiceSummary] = Field(default_factory=list)


class SupervisorNodeServiceActionResult(BaseModel):
    action: str
    node_id: str
    service_id: str
    result: dict[str, object] = Field(default_factory=dict)


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


class SupervisorCoreRuntimeSummary(BaseModel):
    runtime_id: str
    runtime_name: str
    runtime_kind: str = "core_service"
    management_mode: str = "monitor"
    desired_state: str
    runtime_state: str
    lifecycle_state: str
    health_status: str
    freshness_state: str = "unknown"
    host_id: str | None = None
    hostname: str | None = None
    registered_at: str | None = None
    updated_at: str | None = None
    last_seen_at: str | None = None
    last_action: str | None = None
    last_action_at: str | None = None
    last_error: str | None = None
    running: bool | None = None
    resource_usage: dict[str, object] = Field(default_factory=dict)
    runtime_metadata: dict[str, object] = Field(default_factory=dict)


class SupervisorCoreRuntimeRegistrationRequest(BaseModel):
    runtime_id: str
    runtime_name: str
    runtime_kind: str = "core_service"
    management_mode: str = "monitor"
    host_id: str | None = None
    hostname: str | None = None
    desired_state: str = "running"
    runtime_state: str = "running"
    lifecycle_state: str = "running"
    health_status: str = "unknown"
    last_error: str | None = None
    running: bool | None = True
    resource_usage: dict[str, object] = Field(default_factory=dict)
    runtime_metadata: dict[str, object] = Field(default_factory=dict)


class SupervisorCoreRuntimeHeartbeatRequest(BaseModel):
    runtime_id: str
    host_id: str | None = None
    hostname: str | None = None
    runtime_state: str | None = None
    lifecycle_state: str | None = None
    health_status: str | None = None
    last_error: str | None = None
    running: bool | None = None
    resource_usage: dict[str, object] = Field(default_factory=dict)
    runtime_metadata: dict[str, object] = Field(default_factory=dict)


class SupervisorCoreRuntimeActionResult(BaseModel):
    action: str
    runtime: SupervisorCoreRuntimeSummary


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

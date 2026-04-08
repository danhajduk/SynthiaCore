# Supervisor Domain Models

Status: Implemented

This document defines the current Supervisor domain models exposed by the migration foundation in code.

## Source Of Truth

- `backend/app/supervisor/models.py`
- `backend/app/supervisor/service.py`
- `backend/app/supervisor/router.py`
- `backend/app/supervisor/runtime_store.py`

## Models

### HostIdentitySummary

- `host_id`
- `hostname`
- `runtime_provider`
- `managed_runtime_type`

### HostResourceSummary

- `uptime_s`
- `load_1m`
- `load_5m`
- `load_15m`
- `cpu_percent_total`
- `cpu_cores_logical`
- `memory_total_bytes`
- `memory_available_bytes`
- `memory_percent`
- `root_disk_total_bytes`
- `root_disk_free_bytes`
- `root_disk_percent`

Current implementation reuses the existing Core stats collector as a compatibility source while the host-local logic is moved behind Supervisor boundaries in later tasks.

### ManagedNodeSummary

- `node_id`
- `runtime_kind`
- `desired_state`
- `runtime_state`
- `health_status`
- `active_version`
- `running`

Current implementation maps host-local standalone addon runtimes into the Supervisor-managed node summary model.

### SupervisorRegisteredRuntimeSummary

Status: Implemented

This model represents a real Supervisor-managed Node runtime and is separate from the compatibility-era standalone addon runtime summary model.

Returned by:

- `POST /api/supervisor/runtimes/register`
- `POST /api/supervisor/runtimes/heartbeat`
- `GET /api/supervisor/runtimes/{node_id}`

Included in:

- `GET /api/supervisor/runtimes`

Fields include:

- `node_id`
- `node_name`
- `node_type`
- `runtime_kind`
- `desired_state`
- `runtime_state`
- `lifecycle_state`
- `health_status`
- `freshness_state`
- `host_id`
- `hostname`
- `api_base_url`
- `ui_base_url`
- `health_detail`
- `registered_at`
- `updated_at`
- `last_seen_at`
- `last_action`
- `last_action_at`
- `last_error`
- `running`
- `resource_usage`
- `runtime_metadata`

### SupervisorRuntimeRegistrationRequest

Status: Implemented

Accepted by:

- `POST /api/supervisor/runtimes/register`

Purpose:

- register or refresh a real Node runtime with the local Supervisor
- establish the Supervisor-owned runtime identity and local state view

### SupervisorRuntimeHeartbeatRequest

Status: Implemented

Accepted by:

- `POST /api/supervisor/runtimes/heartbeat`

Purpose:

- refresh runtime liveness
- update runtime state, health, and resource usage
- keep heartbeat freshness under Supervisor ownership

### SupervisorRuntimeActionResult

Status: Implemented

Returned by:

- `POST /api/supervisor/runtimes/{node_id}/start`
- `POST /api/supervisor/runtimes/{node_id}/stop`
- `POST /api/supervisor/runtimes/{node_id}/restart`

Includes:

- `action`
- `runtime`

## Compatibility Service Boundary

Status: Implemented

The Supervisor domain service now also acts as the compatibility boundary for host-local collection that still feeds Core-owned routes.

Current compatibility methods:

- `system_stats()`
- `system_snapshot()`
- `process_stats()`

Current compatibility consumers:

- `backend/app/system/stats/router.py`
- `backend/app/system/sampler.py`

This keeps existing Core routes stable while shifting host-local inspection behind the Supervisor service layer.

### SupervisorHealthSummary

Returned by:

- `GET /api/supervisor/health`

Includes:

- `status`
- `host`
- `resources`
- `managed_node_count`
- `healthy_node_count`
- `unhealthy_node_count`

### SupervisorInfoSummary

Returned by:

- `GET /api/supervisor/info`

Includes:

- `supervisor_id`
- `host`
- `resources`
- `boundaries`
- `managed_node_count`
- `managed_nodes`

### SupervisorRuntimeSummary

Returned by:

- `GET /api/supervisor/runtime`

Includes:

- `host`
- `resources`
- `process`
- `managed_node_count`
- `managed_nodes`

### SupervisorAdmissionContextSummary

Returned by:

- `GET /api/supervisor/admission`

Includes:

- `admission_state`
- `execution_host_ready`
- `unavailable_reason`
- `host_busy_rating`
- `total_capacity_units`
- `available_capacity_units`
- `managed_node_count`
- `healthy_managed_node_count`

### SupervisorRuntimeState (Cloudflared)

Status: Implemented

Returned by:

- `GET /api/supervisor/runtime/{runtime_id}`

Notes:

- `runtime_id=cloudflared` returns a runtime state payload with `exists=true`.
- Other runtime ids currently return `{ "exists": false }`.

### SupervisorRuntimeApplyResult (Cloudflared)

Status: Implemented

Returned by:

- `POST /api/supervisor/runtime/{runtime_id}/apply`

Notes:

- `runtime_id=cloudflared` applies the rendered tunnel configuration and returns `ok`, `runtime_state`, and `config_path`.
- Unsupported runtime ids return `{ "ok": false, "runtime_state": "unsupported" }`.

### Supervisor Host API Surface

Status: Implemented

Current Supervisor routes:

- `GET /api/supervisor/health`
- `GET /api/supervisor/info`
- `GET /api/supervisor/resources`
- `GET /api/supervisor/runtime`
- `GET /api/supervisor/runtime/{runtime_id}`
- `POST /api/supervisor/runtime/{runtime_id}/apply`
- `GET /api/supervisor/admission`
- `GET /api/supervisor/nodes`
- `POST /api/supervisor/nodes/{node_id}/start`
- `POST /api/supervisor/nodes/{node_id}/stop`
- `POST /api/supervisor/nodes/{node_id}/restart`
- `POST /api/supervisor/runtimes/register`
- `POST /api/supervisor/runtimes/heartbeat`
- `GET /api/supervisor/runtimes`
- `GET /api/supervisor/runtimes/{node_id}`
- `POST /api/supervisor/runtimes/{node_id}/start`
- `POST /api/supervisor/runtimes/{node_id}/stop`
- `POST /api/supervisor/runtimes/{node_id}/restart`

Supervisor service probes:

- `GET /health`
- `GET /ready`

Schemas:

- [../json_schema/supervisor.models.schema.json](../json_schema/supervisor.models.schema.json)
- [../json_schema/supervisor.api.schema.json](../json_schema/supervisor.api.schema.json)

## Ownership Boundary

Current Supervisor ownership:

- host monitoring and runtime resource summaries
- admission context reporting
- host-local standalone runtime realization
- standalone workload lifecycle execution
- real Node runtime registration
- real Node heartbeat freshness tracking
- real Node runtime state projection
- real Node runtime action intent tracking

Current Core-owned dependencies:

- global governance and scheduler policy
- node trust and onboarding authority
- operator UI and control-plane APIs

Explicit non-goals in the current repository state:

- OS administration
- package management
- general service management outside Hexe-managed runtimes
- firewall and network policy
- non-Hexe orchestration

Future expansion path:

- broader host-local workload supervision
- managed worker execution ownership
- richer reconciliation loops
- runtime backends beyond compose

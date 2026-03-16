# Supervisor Domain Models

Status: Implemented

This document defines the current Supervisor domain models exposed by the migration foundation in code.

## Source Of Truth

- `backend/app/supervisor/models.py`
- `backend/app/supervisor/service.py`
- `backend/app/supervisor/router.py`

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

### Supervisor Host API Surface

Status: Implemented

Current Supervisor routes:

- `GET /api/supervisor/health`
- `GET /api/supervisor/info`
- `GET /api/supervisor/resources`
- `GET /api/supervisor/runtime`
- `GET /api/supervisor/admission`
- `GET /api/supervisor/nodes`
- `POST /api/supervisor/nodes/{node_id}/start`
- `POST /api/supervisor/nodes/{node_id}/stop`
- `POST /api/supervisor/nodes/{node_id}/restart`

## Ownership Boundary

Current Supervisor ownership:

- host-local standalone runtime realization
- host-local worker/process execution helpers
- desired-to-runtime reconciliation
- standalone workload lifecycle execution

Current Core-owned dependencies:

- global governance and scheduler policy
- node trust and onboarding authority
- operator UI and control-plane APIs

# Supervisor Workload Admission

Status: Implemented

This document defines the Supervisor-aware workload admission context used by Core scheduler flows during the migration.

## Source Of Truth

- `backend/app/supervisor/models.py`
- `backend/app/supervisor/service.py`
- `backend/app/supervisor/router.py`
- `backend/app/system/scheduler/router.py`

## Purpose

- Give Core scheduler logic a host-runtime readiness view from Supervisor.
- Reuse Supervisor resource state and managed-node health instead of duplicating host-local checks in Core.
- Keep scheduler ownership in Core while making admission decisions aware of Supervisor runtime state.

## API Surface

- `GET /api/supervisor/admission`

Current response fields:

- `admission_state`
- `execution_host_ready`
- `unavailable_reason`
- `host_busy_rating`
- `total_capacity_units`
- `available_capacity_units`
- `managed_node_count`
- `healthy_managed_node_count`

## Current Scheduling Integration

Status: Implemented

- Scheduler queue dispatch computes its usual Core busy/capacity view.
- When a Supervisor service is available, dispatch also reads Supervisor admission context.
- Available dispatch capacity is capped by `available_capacity_units` from Supervisor admission.
- If `execution_host_ready` is false, queued jobs are deferred instead of being admitted.
- Jobs with `constraints.target_runtime=supervisor` or `constraints.execution_target=host_local|supervisor` are additionally deferred when Supervisor-managed execution targets are unhealthy.

## Boundary

- Core still owns queueing, policy, and orchestration.
- Supervisor supplies host-runtime readiness and execution-target health.
- This is an additive migration step, not the final distributed execution contract.

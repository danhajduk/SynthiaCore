# Node Scheduled Work Execution Contract

Status: Implemented (baseline lease protocol), Partially implemented (node-specialized rollout)

This document defines the canonical execution contract for scheduled work when a node participates as an execution client.

## Source Of Truth

- `backend/app/system/scheduler/router.py`
- `backend/app/system/scheduler/engine.py`
- `backend/app/system/scheduler/models.py`
- `backend/app/system/worker/runner.py`

## Baseline Contract

The current node execution contract reuses the existing scheduler lease protocol rather than introducing a second node-only schema.

Queue-based admission in Core also supports an optional budget-reservation envelope through the existing job-intent payload. Budget-aware queue submissions can include `payload.budget_scope` so Core persists node/customer/provider reservations before work dispatch. Successful queue completion may also report optional `actual_money_spend` and `actual_compute_spend` values when finalizing those reservations.

Current routes:

- `POST /api/system/scheduler/leases/request`
- `POST /api/system/scheduler/leases/{lease_id}/heartbeat`
- `POST /api/system/scheduler/leases/{lease_id}/report`
- `POST /api/system/scheduler/leases/{lease_id}/complete`
- `POST /api/system/scheduler/leases/{lease_id}/revoke`

## Claim / Receive Work

- Execution clients claim work by calling `POST /api/system/scheduler/leases/request`.
- Request body uses:
  - `worker_id`
  - `capabilities[]` (reserved for future capability-based dispatch)
  - `max_units`
- Response is either:
  - denied with `reason` and `retry_after_ms`
  - granted with `lease` and `job`

## Heartbeat

- Active leased work must heartbeat through `POST /api/system/scheduler/leases/{lease_id}/heartbeat`.
- Heartbeat requires the same `worker_id` that claimed the lease.
- The server extends `expires_at` on successful heartbeat.
- If heartbeats stop, the lease expires and the job transitions to `expired`.

## Progress Reporting

- Execution clients may publish progress through `POST /api/system/scheduler/leases/{lease_id}/report`.
- Current report fields:
  - `worker_id`
  - `progress`
  - `metrics`
  - `message`

## Completion / Failure

- Execution clients finalize leased work through `POST /api/system/scheduler/leases/{lease_id}/complete`.
- `status` is `completed` or `failed`.
- Completion removes the active lease and updates the job state accordingly.

## Core-Initiated Revoke

- Core may revoke a lease through `POST /api/system/scheduler/leases/{lease_id}/revoke`.
- Revocation marks the leased job failed and removes the active lease.

## Timeout / Error Semantics

- Unknown lease: `404`
- `worker_id` mismatch: `403`
- No capacity or no eligible work: lease request denial with retry guidance
- Expired lease: execution client must treat it as no longer valid and request new work

## Node Mapping Rule

- During migration, a node acts as an execution client under the existing `worker_id` field.
- Future node-specialized execution APIs must remain compatible with this baseline lease lifecycle unless a later major contract revision replaces it explicitly.

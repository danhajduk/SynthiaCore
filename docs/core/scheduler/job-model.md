# Scheduler Job Model

This document describes the scheduler job and lease models verified in the current repository.

Primary code:
- `backend/app/system/scheduler/models.py`
- `backend/app/system/scheduler/router.py`

## Base Job Model

Status: Implemented

The base scheduler `Job` model includes:

- `job_id`
- `type`
- `priority`
- `requested_units`
- `unique`
- `state`
- `payload`
- `idempotency_key`
- `tags`
- `max_runtime_s`
- `lease_id`
- `created_at`
- `updated_at`

Base job states:

- `queued`
- `leased`
- `running`
- `completed`
- `failed`
- `expired`

Base priorities:

- `high`
- `normal`
- `low`
- `background`

## Lease Model

Status: Implemented

Each lease includes:

- `lease_id`
- `job_id`
- `worker_id`
- `capacity_units`
- `issued_at`
- `expires_at`
- `last_heartbeat`

Lease APIs support request, heartbeat, completion, progress reporting, and revocation.

## Queue Job Intent Model

Status: Implemented

The queue-persistence path also defines `JobIntent`, which adds:

- `addon_id`
- `job_type`
- `cost_units`
- `constraints`
- `expected_duration_sec`
- `time_sensitive`
- `earliest_start_at`
- `deadline_at`
- `max_runtime_sec`
- queue state tracking fields such as `attempts`, `next_earliest_start_at`, and `lease_id`

Queue job intent states:

- `QUEUED`
- `DISPATCHING`
- `RUNNING`
- `DONE`
- `FAILED`
- `CANCELED`

## Runtime Behavior

Status: Implemented

- On startup, persisted jobs are reloaded.
- Jobs found in `DISPATCHING` or `RUNNING` are reset to `QUEUED` during rehydration.
- Background loops handle expiration ticks and dispatch ticks.

## Workload Boundary

Status: Implemented

- Queue jobs and leases describe Core-side admission and orchestration state.
- A lease grants permission for execution work to proceed; it is not itself the execution runtime.
- Current execution helpers consume leases after Core admission, which keeps scheduler ownership separate from runtime ownership.
- Queue dispatch now also considers Supervisor admission context for host readiness and managed execution-target availability.

## See Also

- [README.md](./README.md)
- [../operators-guide.md](../operators-guide.md)
- [../api/api-reference.md](../api/api-reference.md)

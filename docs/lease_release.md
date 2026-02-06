# Lease Release Contract

This document defines how workers complete a lease and release capacity.

## Purpose
- Mark a job as completed or failed.
- Release leased capacity immediately.
- Stop heartbeat requirements for the lease.

## Endpoint
- `POST /api/system/scheduler/leases/{lease_id}/complete`

### Request Body
```json
{
  "worker_id": "worker-123",
  "status": "completed",
  "result": {"output": "..."},
  "error": null
}
```

### Response
```json
{
  "ok": true
}
```

## Status Values
- `completed`
- `failed`

## State Transitions
- On completion: `running` -> `completed`
- On failure: `running` -> `failed`
- If the job is still `leased`, completion will still finalize it.

## Behavior
- The lease is removed from the active lease set.
- Capacity is released immediately.
- The job state is updated and timestamped.

## Error Handling
- If the lease is not found, the server returns `ok: true` and treats it as a no-op.
- If `worker_id` does not match the lease, the server returns `403` (`worker_mismatch`).

## Idempotency
- Completion is idempotent. Repeating completion for the same lease is safe.

## Notes
- Workers should stop heartbeats after completion.
- Use `failed` when the job could not be completed, optionally including `error`.

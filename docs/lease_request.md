# Lease Request Contract (Scheduler API)

This document defines how workers request leases and receive jobs from the scheduler.

## Purpose
- Allow workers to pull work when capacity is available.
- Enforce capacity and busy-rating gates.
- Provide explicit denial reasons and retry guidance.

## Endpoint
- `POST /api/system/scheduler/leases/request`

### Request Body
```json
{
  "worker_id": "worker-123",
  "max_units": 8
}
```

Fields:
- `worker_id` (required): Unique worker identifier.
- `max_units` (optional): Cap the maximum units this worker can accept.

### Response (Granted)
```json
{
  "denied": false,
  "lease": {
    "lease_id": "...",
    "job_id": "...",
    "worker_id": "worker-123",
    "capacity_units": 4,
    "issued_at": "2026-02-06T20:10:00.000Z",
    "expires_at": "2026-02-06T20:11:00.000Z",
    "last_heartbeat": "2026-02-06T20:10:00.000Z"
  },
  "job": {
    "job_id": "...",
    "type": "generic",
    "priority": "normal",
    "requested_units": 4,
    "unique": false,
    "state": "leased",
    "payload": {},
    "idempotency_key": null,
    "tags": [],
    "max_runtime_s": null,
    "lease_id": "...",
    "created_at": "2026-02-06T20:09:30.000Z",
    "updated_at": "2026-02-06T20:10:00.000Z"
  }
}
```

### Response (Denied)
```json
{
  "denied": true,
  "reason": "No capacity (busy=8, usable=10, leased=10)",
  "retry_after_ms": 1500
}
```

## Decision Rules
- Capacity is computed from busy rating and total units.
- If `available <= 0`, the request is denied.
- Jobs are dequeued by priority.
- If the next job’s required units exceed available, it is re-queued and the request is denied.
- If a job is marked `unique` and the worker already holds a lease, the job is skipped for that worker.

## State Transitions
- On grant: `queued` -> `leased`
- On first heartbeat: `leased` -> `running`

## Retry Guidance
- `retry_after_ms` is provided when denied and should be honored by workers.

## Notes
- This is a pull-based model: workers request leases; the scheduler does not push.
- Requests are safe to retry.

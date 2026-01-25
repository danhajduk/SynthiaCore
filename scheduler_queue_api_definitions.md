# Scheduler Queue API — Endpoint & Schema Definitions

This document translates **scheduler_queue_definitions.md** into concrete **HTTP API endpoints**
with **request/response schemas**, plus notes on **DB-backed stats/audit**.

Base path: `/api/scheduler`

Conventions:
- `job_id`, `lease_id` are UUID strings.
- Timestamps are ISO-8601 UTC strings (e.g. `2025-12-28T20:15:00Z`).
- All endpoints return JSON.
- Errors return `{ "detail": "...", "code": "..." }` with appropriate HTTP status.

---

## Enums

### Priority
- `LOW`
- `NORMAL`
- `HIGH`
- `URGENT`

### JobState
- `QUEUED`
- `CLAIMED`
- `PREPARING`
- `LEASE_PENDING`
- `RUNNING`
- `DONE`
- `FAILED`
- `CANCELED`
- `TIMEOUT`

### LeaseState
- `ACTIVE`
- `EXPIRED`
- `RELEASED`

### FinalStatus
- `SUCCEEDED`
- `FAILED`
- `CANCELED`
- `TIMEOUT`

---

## Core Types

### Constraints
```json
{
  "cpu_heavy": true,
  "gpu_required": false,
  "network_heavy": false,
  "disk_write_heavy": false
}
```

### JobIntent (server representation)
```json
{
  "job_id": "uuid",
  "addon_id": "visuals",
  "job_type": "load30",
  "priority": "NORMAL",
  "cost_units": 30,
  "constraints": { "cpu_heavy": true },
  "payload": { "anything": "opaque" },
  "state": "QUEUED",
  "created_at": "2025-12-28T20:15:00Z",
  "updated_at": "2025-12-28T20:15:00Z",
  "claimed_by": null,
  "claim_expires_at": null,
  "lease_id": null,
  "attempts": 0,
  "next_retry_at": null
}
```

### Lease (server representation)
```json
{
  "lease_id": "uuid",
  "job_id": "uuid",
  "addon_id": "visuals",
  "cost_units": 30,
  "ttl_sec": 30,
  "state": "ACTIVE",
  "granted_at": "2025-12-28T20:16:10Z",
  "last_heartbeat_at": "2025-12-28T20:16:25Z",
  "expires_at": "2025-12-28T20:16:40Z"
}
```

### JobResult (terminal)
```json
{
  "job_id": "uuid",
  "status": "SUCCEEDED",
  "result_data": { "path": "/runtime/out.jpg" },
  "error": null,
  "started_at": "2025-12-28T20:16:10Z",
  "finished_at": "2025-12-28T20:17:05Z",
  "attempts": 1
}
```

---

# JOBS API

## 1) Submit a job (addon_core → scheduler)
**POST** `/jobs/submit`

Request:
```json
{
  "addon_id": "visuals",
  "job_type": "load30",
  "priority": "NORMAL",
  "cost_units": 30,
  "constraints": { "cpu_heavy": true },
  "payload": { "model": "sdxl", "prompt": "..." },
  "client_request_id": "optional-idempotency-key"
}
```

Response `201`:
```json
{
  "job": { "...JobIntent..." }
}
```

Errors:
- `400` invalid schema / cost_units <= 0
- `409` duplicate `client_request_id` (if idempotency enabled)

---

## 2) Claim a job (addon_worker → scheduler)
**POST** `/jobs/claim`

Purpose: atomic claim to prevent double execution.

Request:
```json
{
  "addon_id": "visuals",
  "worker_id": "visuals-worker-01",
  "limit": 1,
  "accept_job_types": ["load30", "render_image"],
  "max_cost_units": 40,
  "constraints_capabilities": { "gpu_available": false }
}
```

Response `200` (one claimed):
```json
{
  "job": { "...JobIntent (state=CLAIMED)..." }
}
```

Response `204` (none available).

Notes:
- Scheduler sets `claimed_by`, `claim_expires_at` (e.g. now+60s).
- If worker dies, scheduler requeues when claim expires.

---

## 3) Get job status (addon_core/worker)
**GET** `/jobs/{job_id}`

Response `200`:
```json
{
  "job": { "...JobIntent..." },
  "result": { "...JobResult or null..." }
}
```

Errors:
- `404` not found

---

## 4) Update job state/progress note (worker → scheduler)
**POST** `/jobs/{job_id}/status`

Request:
```json
{
  "state": "PREPARING",
  "note": "warming model cache",
  "progress": 0.15
}
```

Response `200`:
```json
{ "job": { "...JobIntent..." } }
```

Rules:
- Scheduler enforces legal transitions (e.g. CLAIMED→PREPARING ok; DONE→PREPARING no).
- `progress` is best-effort and may be ignored unless RUNNING.

---

## 5) Cancel a job (addon_core → scheduler)
**POST** `/jobs/{job_id}/cancel`

Request:
```json
{
  "reason": "user aborted"
}
```

Response `200`:
```json
{ "job": { "...JobIntent (state=CANCELED)..." } }
```

Cancellation semantics:
- If job is `QUEUED/CLAIMED/PREPARING/LEASE_PENDING` → scheduler cancels immediately.
- If `RUNNING` → scheduler marks as cancellation requested (optional) and worker must respect it,
  or scheduler finalizes as `CANCELED` when lease is released.

---

## 6) List/search jobs (admin/debug + addon_core dashboards)
**GET** `/jobs`

Query params (all optional):
- `state=QUEUED`
- `addon_id=visuals`
- `created_after=...`
- `created_before=...`
- `limit=50`
- `cursor=...` (if you want pagination)

Response `200`:
```json
{
  "jobs": [ { "...JobIntent..." } ],
  "next_cursor": null
}
```

---

## 7) Job events/audit (optional but recommended)
**GET** `/jobs/{job_id}/events`

Response `200`:
```json
{
  "events": [
    { "ts": "2025-12-28T20:15:00Z", "type": "JOB_SUBMITTED", "data": { "priority": "NORMAL" } },
    { "ts": "2025-12-28T20:16:00Z", "type": "JOB_CLAIMED", "data": { "worker_id": "visuals-worker-01" } }
  ]
}
```

---

# LEASES API

## 1) Request a lease (worker → scheduler)
**POST** `/lease/request`

Request:
```json
{
  "job_id": "uuid",
  "addon_id": "visuals",
  "job_type": "load30",
  "cost_units": 30,
  "priority": "NORMAL",
  "constraints": { "cpu_heavy": true },
  "ttl_sec": 30
}
```

Response `200` approved:
```json
{
  "approved": true,
  "lease": { "...Lease (ACTIVE)..." }
}
```

Response `200` denied:
```json
{
  "approved": false,
  "retry_after_sec": 10,
  "reason": "Capacity exceeded: used=60, requested=30, capacity=70"
}
```

Side effects:
- On approval, scheduler sets job `RUNNING`, attaches `lease_id`, `started_at`.
- On denial, job remains `LEASE_PENDING` and scheduler may set `next_retry_at`.

---

## 2) Heartbeat (worker → scheduler)
**POST** `/lease/{lease_id}/heartbeat`

Request:
```json
{
  "job_id": "uuid",
  "worker_id": "visuals-worker-01",
  "progress": 0.65,
  "message": "rendering step 23/35"
}
```

Response `200`:
```json
{
  "lease": { "...Lease..." },
  "job": { "...JobIntent..." }
}
```

Errors:
- `404` unknown lease
- `409` lease not ACTIVE (expired/released)

---

## 3) Release lease (worker → scheduler)
**POST** `/lease/{lease_id}/release`

Request:
```json
{
  "job_id": "uuid",
  "worker_id": "visuals-worker-01",
  "status": "SUCCEEDED",
  "result_data": { "path": "/runtime/published/current.jpg" },
  "error": null,
  "metrics": { "runtime_ms": 41234, "peak_mem_mb": 2870 }
}
```

Response `200`:
```json
{
  "lease": { "...Lease (RELEASED)..." },
  "job": { "...JobIntent (DONE/FAILED/etc)..." },
  "result": { "...JobResult..." }
}
```

Rules:
- Release finalizes the job into a terminal state.
- If lease expired before release, scheduler may return `409` and finalize as TIMEOUT.

---

## 4) Get lease status (debug)
**GET** `/lease/{lease_id}`

Response `200`:
```json
{ "lease": { "...Lease..." } }
```

---

# STATS / DB UTILIZATION

You said: *“we are using db for stats”* — yes, we should leverage that here.
Even if queue/leases are in-memory initially, **stats and events should be persisted**,
because they’re the difference between “works” and “diagnosable at 3 AM”.

## Recommended DB tables (minimal)

### scheduler_job_runs (facts / results)
One row per job_id (updated as job progresses):
- job_id (pk)
- addon_id, job_type
- priority, cost_units
- state (current)
- attempts
- created_at, started_at, finished_at
- claimed_by
- lease_id (last)
- final_status
- error_text (nullable)
- result_json (nullable)
- metrics_json (nullable)

### scheduler_lease_runs (facts)
One row per lease_id:
- lease_id (pk)
- job_id (fk)
- addon_id
- cost_units, ttl_sec
- granted_at, last_heartbeat_at, released_at, expires_at
- state
- release_status (nullable)

### scheduler_events (append-only audit)
Append-only stream:
- id (pk)
- ts
- entity_type (JOB|LEASE)
- entity_id (job_id/lease_id)
- event_type
- data_json

Why:
- event streams make UI timelines trivial
- post-mortems become possible

## Stats endpoints (optional but handy)

### Current snapshot
**GET** `/stats/snapshot`

Response `200`:
```json
{
  "capacity": { "total": 70, "used": 60, "reserved": 0 },
  "jobs": { "queued": 4, "running": 2, "failed_last_24h": 1 },
  "leases": { "active": 2, "expired_last_24h": 0 }
}
```

### Time-series (DB-backed)
**GET** `/stats/timeseries?metric=leases_active&bucket=5m&range=24h`

Response `200`:
```json
{
  "metric": "leases_active",
  "bucket": "5m",
  "points": [
    { "ts": "2025-12-28T00:00:00Z", "value": 1 },
    { "ts": "2025-12-28T00:05:00Z", "value": 2 }
  ]
}
```

---

# Guardrails (non-negotiable if you want sanity)

- **Claim is atomic**: only one worker can claim a job.
- **Lease is required**: worker must not do heavy work without it.
- **Heartbeat enforces reality**: missing HB → lease expiry → job TIMEOUT (or requeue if you choose).
- **Release finalizes job**: treat lease release as the authoritative completion signal.
- **DB event log**: persist lifecycle events for debugging and UI history.

---

## Status

These endpoints + schemas form the **authoritative API contract**
for the Scheduler Queue + Worker + Lease flow.

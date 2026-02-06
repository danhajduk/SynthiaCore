# Queueing & Dispatch Logic (Future / Optional)

This document specifies the **queue layer** that can be added on top of the current
**no-queue (admission-only)** scheduler.

Today (MVP):
- Scheduler answers **approve/deny** immediately.
- Callers retry based on `retry_after_sec`.
- No backlog exists in the scheduler.

When to add a queue:
- You need *eventual execution* (jobs must run later even if denied now).
- You need fairness across addons (avoid retry-spam winning).
- You want centralized ordering (FIFO / priority).
- You want “run this overnight when quiet”.

---

## 1) Principles

- The queue stores **job intents**, not workers.
- Admission policy stays the source of truth:
  - quiet state / streak / capacity / safety caps
- Dispatch happens when conditions change:
  - a lease releases/expires
  - quiet state becomes better
  - capacity increases
  - a timer triggers periodic re-check

---

## 2) New Concepts

### 2.1 Job Intent
A job intent is a durable record that describes the job to run.

Minimal fields:
- `job_id` (uuid)
- `addon_id`
- `job_type`
- `cost_units`
- `priority`
- `constraints`
- `expected_duration_sec` (optional)
- `created_at`
- `state`: `QUEUED | DISPATCHING | RUNNING | DONE | FAILED | CANCELED`
- `attempts`
- `next_earliest_start_at` (backoff / schedule)
- `lease_id` (when RUNNING)

Optional fields:
- `payload` (JSON) — job-specific input (opaque to scheduler)
- `time_sensitive`: bool (or deadline)
- `deadline_at`
- `max_runtime_sec` (hard timeout)
- `tags` (for filtering / UI)
- `pid` (if worker registers it)

### 2.2 Queue Store
MVP queue store can be **in-memory**; production should be **SQLite**.

Recommended tables (SQLite):
- `scheduler_jobs`
- `scheduler_job_events` (audit trail)
- `scheduler_leases` (optional, or keep leases separate)

---

## 3) API Surface (Queue Mode)

### 3.1 Submit a job intent
```
POST /api/system/scheduler/queue/jobs/submit
```

Body = same as lease request + optional scheduling fields:

```json
{
  "addon_id": "visuals",
  "job_type": "indexing",
  "cost_units": 30,
  "priority": "NORMAL",
  "constraints": {"cpu_heavy": true, "disk_write_heavy": false, "network_heavy": false},
  "expected_duration_sec": 120,

  "payload": {"path": "/some/dir"},
  "time_sensitive": false,
  "earliest_start_at": "2025-12-28T23:00:00Z"
}
```

Response:
```json
{
  "job_id": "…",
  "state": "QUEUED"
}
```

### 3.2 Query job status
```
GET /api/system/scheduler/queue/jobs/{job_id}
```

### 3.3 Cancel a job
```
POST /api/system/scheduler/queue/jobs/{job_id}/cancel
```

### 3.4 List queue (admin/debug)
```
GET /api/system/scheduler/queue/jobs?state=QUEUED&limit=50
```

---

## 4) Dispatch Model

There are two viable models. Pick one.

### Model A (recommended): Addon-managed workers + scheduler-managed queue
- Scheduler owns the job queue and decides **when a job may start**.
- Addon owns worker lifecycle (spawn/stop).
- When a job becomes eligible, scheduler returns “DISPATCH” and addon starts/activates a worker.

Flow:
1. Addon submits job intent (`/jobs/submit`) and gets `job_id`.
2. Scheduler dispatcher marks job `DISPATCHING` when admission passes.
3. Scheduler notifies addon OR addon polls for dispatchable jobs.
4. Addon spawns/activates worker for that `job_id`.
5. Worker requests a **lease** (or scheduler grants lease as part of dispatch).
6. Job becomes `RUNNING`, linked to `lease_id`.
7. Worker heartbeats lease; on completion, releases lease.
8. Addon reports completion; scheduler marks `DONE/FAILED`.

Pros:
- Keeps scheduler lightweight.
- Addons can implement custom worker pools.
- Works well in a plugin ecosystem.

Cons:
- Requires polling or a notification channel.

### Model B: Scheduler starts workers (central runner)
- Scheduler launches processes itself (knows PID).
- Strong enforcement (easy kill on timeout).
- More complex permissions/sandboxing.

Given open-source + addon ecosystem, Model A is usually safer.

---

## 5) Dispatcher Loop

A single background loop can periodically try to dispatch queued jobs.

### Trigger conditions
- Timer tick (e.g., every 2–5s)
- Lease released/expired (immediate tick)
- Quiet state change event (optional)
- Manual admin “kick” endpoint (optional)

### Pseudocode

```python
def dispatch_tick():
    snap = AGGREGATOR.get_snapshot()
    capacity = calculate_capacity(snap)          # 0..100
    used = sum(active_lease.cost_units for active_lease in active_leases())

    for job in next_jobs_ordered():
        if job.next_earliest_start_at and now < job.next_earliest_start_at:
            continue

        approved, reason, retry = decide_admission_like(job, used, capacity, snap)
        if not approved:
            job.next_earliest_start_at = now + retry_after(reason, retry)
            continue

        # Reserve budget (optional):
        used += job.cost_units

        job.state = "DISPATCHING"
        emit_event(job, "DISPATCHING", reason="admitted")
        notify_addon(job)   # or mark dispatchable for polling
```

### Reservation: yes/no?
- Without reservation, multiple dispatch ticks could over-dispatch.
- With reservation, you ensure budget is not exceeded even before lease is granted.

Simplest approach:
- When job is `DISPATCHING`, treat its cost as “reserved”.
- If addon doesn’t start it within a timeout (e.g., 30s), revert to `QUEUED`.

---

## 6) Ordering & Fairness

### Default ordering
1. Higher `priority` first
2. Earlier `created_at` first (FIFO within priority)

### Anti-starvation
- After N failed attempts, slightly boost priority (“aging”).
- Or ensure each addon gets a minimum share (fair queuing).

### Rate limiting retry spam
In queue mode, addons should not spam `/lease/request`.
Instead they submit a job once; scheduler owns retries.

---

## 7) Time-Sensitive / Deadline Jobs (Optional)

Add fields:
- `deadline_at`
- `time_sensitive` (bool)

Policy:
- If close to deadline, allow dispatch even in NORMAL state
- Still never exceed capacity, but may preempt lower-priority queued work

---

## 8) Interaction with Leases

Two choices:

### 8.1 Job -> Worker -> Lease (recommended)
- Scheduler dispatches job (intent).
- Worker still requests lease before heavy work.
- Lease is the “runtime contract”, job is the “planning record”.

### 8.2 Job dispatch grants lease immediately
- Scheduler creates lease as part of dispatch.
- Worker heartbeats that lease.
- Requires more coordination, but less round-trips.

Start with 8.1.

---

## 9) Observability

Expose:
- queue length by state
- oldest queued job age
- per-addon queued/running counts
- dispatch decisions and reasons

Persist audit events:
- SUBMITTED
- ADMITTED / DENIED (with reason)
- DISPATCHING
- RUNNING (lease_id)
- DONE / FAILED / CANCELED / TIMEOUT

---

## 10) Minimal MVP Queue Checklist

- [x] Add `JobIntent` model
- [x] Add in-memory queue store + endpoints: submit/get/cancel/list
- [x] Add dispatcher loop (timer)
- [x] Add “dispatchable jobs” endpoint for addon polling:
      `GET /api/system/scheduler/queue/dispatchable`
- [x] Add job state transitions + events
- [ ] Add persistence (SQLite) once semantics are stable

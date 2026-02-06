# Worker Lifecycle & Job Execution Model

This document outlines the standard worker flow when pulling jobs from the scheduler.

## Summary
Workers follow a pull-based loop:
1. Request a lease.
2. If granted, start work and begin heartbeats.
3. On completion or failure, complete the lease.
4. If denied, wait `retry_after_ms` and retry.

## Lifecycle Steps

### 1) Request Lease
- `POST /api/system/scheduler/leases/request`
- Provide `worker_id` and optional `max_units`.
- If denied, respect `retry_after_ms`.

### 2) Start Work
- On grant, the job is in `leased` state.
- Start the job and immediately begin heartbeats.
- The first heartbeat transitions the job to `running`.

### 3) Heartbeat Loop
- `POST /api/system/scheduler/leases/{lease_id}/heartbeat`
- Keep `heartbeat_interval_s < lease_ttl_s`.
- Heartbeats extend `expires_at`.

### 4) Complete Lease
- `POST /api/system/scheduler/leases/{lease_id}/complete`
- Provide `status` = `completed` or `failed`.
- Stop heartbeats after completion.

## Failure Handling
- If heartbeats fail, the lease expires server-side.
- If the server restarts, the lease will expire unless heartbeats resume.
- If `worker_id` does not match, requests are rejected with `worker_mismatch`.

## Recommended Worker Loop (Pseudo)
```python
while True:
    res = request_lease(worker_id, max_units)
    if res.denied:
        sleep(res.retry_after_ms / 1000)
        continue

    start_heartbeat_task(res.lease_id)
    try:
        run_job(res.job)
        complete(res.lease_id, status="completed")
    except Exception as e:
        complete(res.lease_id, status="failed", error=str(e))
```

## Notes
- Workers should be idempotent and safe to retry.
- Keep worker IDs stable to support uniqueness constraints.

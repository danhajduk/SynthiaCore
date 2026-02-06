# Lease Heartbeat Contract

This document defines the heartbeat behavior for scheduler leases. Heartbeats keep a lease active and confirm that a worker is still running the job.

## Purpose
- Prevent stranded capacity by expiring leases when workers die or lose connectivity.
- Provide a simple, deterministic liveness signal.
- Drive job state transitions from `leased` to `running`.

## Core Rules
- A lease is granted with an `expires_at` timestamp.
- Workers must send heartbeats before `expires_at` to extend the lease.
- If heartbeats stop, the lease expires and capacity is released.
- The first successful heartbeat transitions the job state from `leased` to `running`.

## Endpoint
- `POST /api/system/scheduler/leases/{lease_id}/heartbeat`

### Request Body
```json
{
  "worker_id": "worker-123"
}
```

### Response
```json
{
  "ok": true,
  "expires_at": "2026-02-06T20:15:30.123Z"
}
```

## Timing
- The server uses a **lease TTL** plus optional **grace** to compute `expires_at`.
- On heartbeat, `expires_at` is extended to `now + lease_ttl_s + heartbeat_grace_s`.
- Heartbeat interval should be **less than the TTL** to avoid accidental expiry.

Recommended:
- `heartbeat_interval_s < lease_ttl_s`
- Add small jitter to avoid synchronized bursts.

## State Transitions
- On lease grant: `queued` -> `leased`
- On first heartbeat: `leased` -> `running`
- On completion: `running` -> `completed` or `failed`
- On missed heartbeats: `leased|running` -> `expired`

## Failure Modes
- If the lease is not found: return `404` (`lease_not_found`).
- If `worker_id` does not match the lease: return `403` (`worker_mismatch`).
- If the server restarts or network drops, the lease will expire server-side.

## Idempotency
- Multiple heartbeats are safe. Each heartbeat simply extends `expires_at`.

## Capacity Impact
- Capacity is held for the life of the lease, and released on expiry or completion.

## Notes
- Heartbeats are required for all active leases, even if the job is quick.
- Clients should stop heartbeats immediately after completing or failing the job.

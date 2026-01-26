# Scheduler Queue & Worker Flow — Definitions

This document defines the **queue-based execution model** for Synthia addons,
splitting responsibilities between **addon_core**, **addon_worker**, and the **scheduler**.

---

## Roles

### addon_core (Planner / Orchestrator)
- Decides *what* work needs to be done.
- Submits jobs to the scheduler queue.
- Tracks job progress and results.
- Does **not** execute heavy work directly.

### addon_worker (Executor)
- Polls scheduler for available jobs.
- Prepares runtime environment.
- Requests resource leases before execution.
- Sends heartbeats while running.
- Releases lease with final status and result data.

### scheduler (Referee / Historian)
- Owns job queue and state machine.
- Enforces system capacity via leases.
- Tracks heartbeats and lease expiry.
- Persists job lifecycle and results.
- Reports status back to addon_core.

---

## Core Objects

### JobIntent
Represents *intent to perform work*.

Fields:
- job_id (uuid)
- addon_id
- job_type
- priority (LOW | NORMAL | HIGH | URGENT)
- cost_units
- constraints (cpu_heavy, gpu_required, etc.)
- payload (opaque JSON)
- created_at
- state

---

### Lease
Represents *permission to consume resources*.

Fields:
- lease_id
- job_id
- addon_id
- cost_units
- ttl_sec
- granted_at
- expires_at
- state (ACTIVE | EXPIRED | RELEASED)

---

### Heartbeat
Liveness + progress signal.

Fields:
- lease_id
- job_id
- progress (optional)
- message (optional)
- timestamp

---

### JobResult
Final outcome reported to addon_core.

Fields:
- job_id
- status (SUCCEEDED | FAILED | CANCELED | TIMEOUT)
- result_data (optional JSON)
- error (optional)
- started_at
- finished_at
- attempts

---

## Job State Machine

QUEUED
→ CLAIMED
→ PREPARING
→ LEASE_PENDING
→ RUNNING
→ DONE | FAILED | CANCELED | TIMEOUT

---

## Execution Flow

### 1. addon_core submits job
- Scheduler creates JobIntent in QUEUED state.

### 2. addon_worker checks queue
- Worker claims job atomically.
- Job moves to CLAIMED.

### 3. addon_worker prepares
- Runtime setup (models, data, mounts).
- Job moves to PREPARING.

### 4. addon_worker requests lease
- Scheduler approves or denies.
- On approval → job moves to RUNNING.
- On denial → retry after backoff.

### 5. addon_worker sends heartbeat
- Maintains lease validity.
- Updates progress.
- Missing HB → lease expiry → TIMEOUT.

### 6. addon_worker releases lease
- Includes final status and optional result data.
- Lease released.
- Job enters terminal state.

### 7. scheduler reports to addon_core
- addon_core polls job status or receives events.
- Final JobResult is available.

---

## Design Notes

- Queue owns *intent*, lease owns *execution*.
- Workers never run heavy work without a lease.
- Scheduler is the single source of truth.
- Backoff is scheduler-directed, not worker-guessing.
- This model prevents retry storms and double execution.

---

## Status

This document defines the **authoritative execution contract**
for queue + worker scheduling in Synthia.

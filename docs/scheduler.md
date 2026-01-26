# Synthia Scheduler Design

## Overview
This document defines the **Scheduler system** for Synthia Core.  
The scheduler is responsible for safely running *heavy* or *costly* work
based on current system load, API pressure, and available capacity.

It uses:
- Busy rating (0–10)
- Capacity units
- Leases + heartbeats
- Priority-aware queues

The goal is **predictable, safe execution** without starving the system.

---

## Core Concepts

### Job
A unit of work that *wants* to run.

**States**
- `queued`
- `leased`
- `running`
- `completed`
- `failed`
- `expired`

Jobs never execute directly — they must acquire a **lease**.

---

### Lease
A temporary permission to consume capacity.

**Properties**
- `lease_id`
- `job_id`
- `capacity_units`
- `expires_at`
- `last_heartbeat`

Leases automatically expire if heartbeats stop.

---

### Capacity Model
System capacity is represented as abstract units.

Example:
- Total capacity: `100`
- Busy rating affects usable capacity:
  - Busy 0 → 100%
  - Busy 5 → 50%
  - Busy 9 → 10%

Capacity is **dynamic**, recalculated every minute.

---

### Busy Rating
A normalized score `0–10` derived from:
- CPU load
- Memory pressure
- API latency
- API inflight requests
- Error rate

Used as a *gate*, not a metric.

---

## Scheduler Flow

1. Job submitted → `queued`
2. Scheduler evaluates:
   - Busy rating
   - Available capacity
   - Job priority
3. If allowed:
   - Lease granted
   - Job → `leased`
4. Worker starts → `running`
5. Worker heartbeats
6. On completion → `completed`
7. On timeout → `expired`

---

## Queues

### Priority Levels
- `high`
- `normal`
- `low`
- `background`

High priority may preempt low-priority jobs.

---

## Heartbeats

Workers must heartbeat every `N` seconds.

If heartbeat expires:
- Lease revoked
- Capacity released
- Job marked `expired`

---

## Failure Modes

- Worker crash → lease expiry
- Busy spike → new leases denied
- Overcommit → queue backpressure

Scheduler must **fail closed**, never open.

---

## Initial Implementation Plan

### Phase 1 – In-Memory Core
- Job model
- Lease model
- Capacity calculator
- Priority queue
- No persistence

### Phase 2 – API Layer
- Submit job
- Request lease
- Heartbeat
- Release lease

### Phase 3 – Persistence
- SQLite or Postgres
- Job history
- Metrics

### Phase 4 – Intelligence
- Smart scheduling
- Time-of-day weighting
- Predictive delays

---

## Design Principles

- Deterministic
- Observable
- Conservative
- Recoverable
- Extensible

---

## Non-Goals (for now)

- Distributed scheduling
- Cross-node leases
- External job runners

---

## Final Notes
This scheduler is the **governor** of Synthia.
If this stays clean, everything else scales safely.

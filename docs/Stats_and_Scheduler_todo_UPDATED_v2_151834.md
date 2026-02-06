# System Stats + Heavy Work Scheduler — TODO

Owner: Core backend  
Goal: Collect system + addon stats, persist history, compute “quiet/idle” windows, and provide a cooperative lease-based scheduler that can approve/block heavy processing.

---

## 0) Definitions / Scope

### MVP (Minimum Viable Product)
The smallest implementation that is useful immediately:
- Provides current stats snapshot + limited history
- Computes quiet_score and a state (QUIET/NORMAL/BUSY/PANIC)
- Exposes a lease API to approve/block heavy work for addons
- Stores enough history to show graphs and detect “quiet streaks”

### Non-goals (for MVP)
- Hard enforcement (cgroups/container CPU limits, etc.)
- Full Prometheus support (optional later)
- Log parsing, eBPF, deep kernel pressure metrics (later)

---

## 1) Data Model (Core)

### 1.1 State Tree (in-memory)
- [x] Define `SystemStatsSnapshot` Pydantic model:
  - [x] `collected_at`
  - [x] `host` (cpu/mem/disk/net/uptime)
  - [x] `process` (rss/cpu/fds/threads)
  - [x] `api` (rps/error_rate/p95_latency) — may be partial in MVP
  - [x] `addons` dict keyed by addon_id
  - [x] `quiet` (quiet_score + state + reasons)
  - [x] `errors` (collector errors, optional debug section)

- [x] Define addon stats model `AddonStatsSnapshot`:
  - [x] lifecycle/runtime state (installed/enabled/loaded/error if available)
  - [x] health status + last_checked + last_ok
  - [x] runtime dir size
  - [x] optional `custom` dict (reserved for addon-provided stats)

### 1.2 Quiet State Machine
- [x] Define quiet states: `QUIET`, `NORMAL`, `BUSY`, `PANIC`
- [x] Define `QuietAssessment` model:
  - [x] `quiet_score` (0–100)
  - [x] `state`
  - [x] `reasons` list (human readable)
  - [x] `inputs` summary (cpu_avg_2m, mem_pct, rps, p95, disk_free_pct, etc.)

---

## 2) Collectors (MVP)

### 2.1 Host Collector
- [x] CPU: total % + load avg (if available)
- [x] Memory: used/free %, swap usage
- [x] Disk: usage per mount (at least `/` and project `data/`)
- [x] Network: bytes in/out per interface (optional MVP)
- [x] Uptime / boot time

### 2.2 Process Collector (Synthia backend process)
- [x] RSS memory
- [x] Process CPU %
- [x] Threads
- [x] Open file descriptors (if supported)

### 2.3 Addon Collector
- [ ] Pull from addon registry/store:
  - [x] installed/enabled/loaded/runtime state
  - [ ] health cache entries (status + timestamps + error codes)
- [ ] Runtime dir size:
  - [x] per addon: `data/addons/<id>/runtime` (or actual runtime root)
  - [ ] ensure directory walk is rate-limited / cached

### 2.4 API Stats Collector (basic)
- [x] Implement middleware to record:
  - [x] request count
  - [x] error count
  - [x] latency histogram or rolling p95 approximation
- [x] Expose as in-memory stats for snapshot

---

## 3) Scheduler / Heavy Work Gatekeeper (MVP)

### 3.1 Concepts
- [x] Cooperative scheduling with a **lease** model:
  - [x] addons request a lease, must heartbeat, then release
  - [x] leases expire if heartbeat stops (TTL)
- [x] Policy uses current quiet assessment to approve/deny
- [x] Policy uses **capacity** (budget units) to allow multiple low-cost jobs concurrently
- [x] **No-queue MVP**:
  - [x] scheduler does not hold a backlog
  - [x] callers must retry when denied (guided by `retry_after_sec`)
  - [ ] optional future: add a priority queue + dispatcher loop (see 3.6)

### 3.2 Models (current)
- [x] `HeavyLeaseRequest`:
  - [x] `addon_id`
  - [x] `job_type`
  - [x] `cost_units` (1–100) **canonical cost metric**
  - [x] `cost_class` (LOW/NORMAL/HIGH) **legacy / optional** (mapped to units if provided)
  - [x] `expected_duration_sec` (optional; informational for now)
  - [x] `priority` (LOW/NORMAL/HIGH) *(API currently expects uppercase values)*
  - [x] `constraints`: `cpu_heavy`, `disk_write_heavy`, `network_heavy`

- [x] `HeavyLeaseResponse`:
  - [x] `approved` bool
  - [x] `lease_id` (if approved)
  - [x] `retry_after_sec` (if denied)
  - [x] `limits` (heartbeat TTL guidance)
  - [x] `reason` (string; should be human-readable and debuggable)

- [x] `LeaseRecord`:
  - [x] `lease_id / addon_id / job_type`
  - [x] `cost_units` (stored for accounting / future auditing)
  - [x] timestamps: `granted_at / last_heartbeat_at / expires_at`
  - [x] `state`: `active/expired/released` *(member names are lowercase; values are uppercase strings)*

### 3.3 Policy (MVP)
- [x] Hard deny if:
  - [x] quiet_state = PANIC (via quiet assessment)
- [x] Soft deny if:
  - [x] quiet_state != QUIET AND priority != HIGH
  - [x] capacity exceeded (units): `used_units + requested_units > capacity_units`
  - [x] optional safety caps: global + per-addon concurrency limits (can remain as backstops)
- [x] Default MVP settings (current intent):
  - [x] heartbeat TTL = 30s
  - [x] capacity calculation keeps headroom for the rest of the system (see `calculate_capacity()`)
  - [x] concurrency backstops (optional): max_global, max_per_addon
- [x] Denial reasons should be explicit:
  - [x] `Capacity exceeded: used=…, requested=…, capacity=…`
  - [x] `System is BUSY; waiting for QUIET`
  - [x] `Recent PANIC detected; cooling down` (once added)

### 3.4 API Endpoints (implemented)
> NOTE: Finalized under `/api/scheduler/*`

- [x] `POST /api/scheduler/lease/request`
- [x] `POST /api/scheduler/lease/{lease_id}/heartbeat`
- [x] `POST /api/scheduler/lease/{lease_id}/release`
- [x] `GET /api/scheduler/status` (active + recent leases, quiet info)
- [x] Add `POST /api/scheduler/lease/{lease_id}/report` (progress + accounting)
- [x] Add `POST /api/scheduler/lease/{lease_id}/revoke` (core-initiated cancel)

### 3.5 Audit / Visibility
- [x] Track lease lifecycle in-memory (active + recent)
- [x] Persist lease events in SQLite (grant/deny/release/expire)
- [x] Expose per-addon decision summary (denies, last reason, cool-down)

### 3.6 Queueing (future, optional)
If/when we need “guaranteed eventual execution” or fairness across addons:
- [x] Add an internal **priority queue** of job intents (not workers)
- [x] A dispatcher loop periodically re-evaluates admission when:
  - leases expire/release
  - quiet state improves
  - capacity increases
- [x] Persistence required if we want crash-safe queues (SQLite)

## 4) Persistence (History Storage) — SQLite
 active heavy job(s)

---

## 4) Persistence (History Storage)

### 4.1 SQLite Storage (recommended)
- [ ] Create DB schema for time-series-ish samples:
  - [ ] table `stats_samples`:
    - timestamp
    - metric_group (host/process/api/quiet/addon:<id>)
    - payload_json (compressed optional later)
- [ ] Write samples on a schedule (not every collector run if too frequent)
- [ ] Retention policy (MVP):
  - [ ] keep last 7 days raw (configurable)
  - [ ] optional downsample later

### 4.2 Quiet Streaks
- [x] Store derived quiet intervals:
  - start_time, end_time, avg_score, min_score
- [x] Provide “last 24h quiet streaks” endpoint or computed on demand

---

## 5) Scheduling / Background Tasks

- [ ] Create stats runner on FastAPI startup:
  - [ ] collector loops (with jitter)
  - [ ] each collector isolated with timeout + exception capture
- [ ] Suggested intervals (MVP):
  - [ ] host/process: 2–5s
  - [ ] api aggregation: per request, report every 5s
  - [ ] addon health snapshot: 15–60s
  - [ ] disk/runtime dir size: 60–120s

- [ ] Ensure shutdown cancels tasks cleanly

---

## 6) API (Stats)

- [x] `GET /api/system-stats/current`
- [x] `GET /api/system-stats/history?group=quiet&range=1h&step=10s`
- [ ] `GET /api/system-stats/addons`
- [x] `GET /api/system-stats/health` (rollup ok/warn/error + reasons)
- [ ] Debug (optional MVP):
  - [ ] `GET /api/system-stats/debug/collectors`

---

## 7) Config + Defaults

- [x] Add config model (env + defaults):
  - [x] intervals
  - [x] retention days
  - [x] quiet thresholds (cpu/mem/rps/p95)
  - [x] heavy scheduler limits (concurrency, TTL, token bucket)

- [x] Provide safe defaults that work on your dev box and on a small NUC

---

## 8) Testing Strategy

- [ ] Unit tests:
  - [ ] quiet score calculation
  - [ ] policy decisions under simulated stats
  - [ ] token bucket behavior
  - [ ] lease expiry without heartbeat
- [ ] Integration tests:
  - [ ] stats runner updates snapshot
  - [ ] endpoints return expected structure

---

## 9) Future Enhancements (Post-MVP)

- [ ] Addon custom stats pull:
  - [ ] `GET /api/addons/{id}/stats` (optional endpoint addons may implement)
- [ ] Downsampling + multi-resolution history
- [ ] Prometheus metrics export
- [ ] Hard enforcement:
  - [ ] cgroups for addon subprocesses
  - [ ] container resource limits
- [ ] Quiet window prediction heatmap (hour-of-day / day-of-week)
- [ ] UI widgets:
  - [ ] header badge: OK/WARN/ERROR
  - [ ] sidebar mini chart
  - [ ] settings: maintenance window + allow/block toggle

---

## 10) Implementation Order (Recommended)

1. [x] Define models for snapshot + quiet assessment
2. [x] Build collectors (host/process/addon)
3. [x] Add API middleware stats
4. [x] Implement in-memory snapshot + `/current`
5. [x] Implement SQLite sample storage + `/history`
6. [ ] Implement heavy scheduler lease endpoints + policy
7. [x] Add quiet streak tracking + `/health` rollup


---

## 12) Dev Notes (practical gotchas)

- When iterating under `uvicorn --reload`, **Enum changes** can sometimes behave oddly due to module caching.
  - If you see impossible enum attribute errors after edits, do a **hard restart** of uvicorn (kill + relaunch).
- Pydantic v2:
  - Prefer `from __future__ import annotations` and avoid quoted forward refs unless you truly need them.
  - If you introduce forward refs across models, `model_rebuild()` is the escape hatch, but the goal is to avoid needing it.

# System Metrics

This document describes how Synthia Core collects, caches, and stores machine + API metrics, and how those metrics are intended to be consumed by the UI and scheduler.

## Overview

Synthia Core produces three “layers” of metrics:

1. **Live System Snapshot (cached)**  
   Updated every 5 seconds and served instantly to the UI via `/api/system/stats/current`.

2. **API Metrics Snapshot (rolling window)**  
   Computed over a rolling window (default 60s). Refreshed on a separate schedule (recommended: every 10s, window 60s).

3. **Minute History (stored)**  
   Every minute (aligned to wall-clock minute boundaries), store a consolidated snapshot + `busy_rating` in SQLite. Retain 24 hours.

This separation keeps the UI responsive and ensures heavy scheduling decisions are stable and explainable.

---

## Live Snapshot

### Endpoint
- `GET /api/system/stats/current`

### Data Includes
- timestamp (epoch seconds, ms precision)
- hostname, uptime
- cpu: total %, per-core %
- load averages: 1/5/15
- memory + swap
- disks: mountpoint usage
- network: counters + computed rates (bytes/sec)
- api: rolling metrics snapshot (may be empty if excluded endpoints only)
- busy_rating: 0..10 (derived signal)

### Update Rate
- **System sampling**: every **5 seconds** (background sampler)
- Endpoint returns **cached snapshot**, not computed on request.

---

## API Metrics

API metrics are collected by middleware and summarized by the ApiMetricsCollector.

### Collection
- Middleware records one event per request (excluding some paths, see below):
  - path, client IP, status
  - request duration (ms)
  - timestamp

### Default Exclusions (not tracked)
- `/api/system/stats...` (to prevent monitoring self-inflation)
- `/docs`
- `/openapi.json`
- (optional) `/api/health` if you want to ignore health probes

### Snapshot Fields
- window_s: rolling window size
- rps: requests / window_s
- inflight: requests currently in-flight
- latency_ms_avg, latency_ms_p95
- error_rate: fraction of requests with status >= 400
- top_paths: (path, count)
- top_clients: (client, count)

### Recommended Schedule
- window_s: **60s**
- refresh interval: **10s**
This keeps the rolling summary up-to-date without being noisy.

---

## Busy Rating (0..10)

`busy_rating` is a derived score used for gating and scheduling heavy work.

### Intended Meaning
- 0–2: idle
- 3–5: normal activity
- 6–7: busy (prefer to defer heavy work)
- 8–10: hot (do not start heavy work)

### Inputs
Typical inputs include:
- API p95 latency (signal of queueing)
- inflight requests (early congestion)
- rps (traffic intensity)
- error rate (stress symptom)
- cpu %
- load per core (scheduler pressure)

### Output Contract
The score is always clamped:
- min: 0.0
- max: 10.0

---

## Minute History Storage

### DB
- SQLite: `data/system_stats.sqlite3` (WAL enabled)

### Table (concept)
- `stats_minute(ts REAL PRIMARY KEY, busy REAL NOT NULL, snapshot_json TEXT NOT NULL)`

### Schedule
- Stored every minute, aligned to minute boundaries:
  - `ts = (floor(now/60)+1)*60`
- Retention: 24 hours (approx 1440 points)

---

## Consumption

### UI
- Primary: poll `/api/system/stats/current` every 5–10 seconds
- Optional: history endpoint for charts/sparklines (planned)

### Scheduler / Heavy Work
- Use `busy_rating` + rolling averages to decide:
  - run now vs defer
  - choose a “quiet window”
  - throttle concurrency

---

## Notes / Gotchas
- First call after process start may have null/empty network rates until a baseline exists.
- Excluding `/api/system/stats` from API metrics is recommended to avoid self-induced “busy” readings.
- Avoid blocking computations inside request handlers; prefer background sampling + cached responses.

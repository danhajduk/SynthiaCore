# SynthiaCore

SynthiaCore is a Core + Addons platform with a built-in scheduler, system metrics, and a frontend that auto-loads addons. This README reflects the current functionality in the repo.

## Highlights
- **Core runtime**: FastAPI backend + React frontend with addon discovery and dynamic routing.
- **Scheduler**: Pull-based leases, capacity-aware, priority queues, idempotent jobs, unique job flag.
- **History + stats**: SQLite-backed job history (30-day retention), stats by addon, success rate, queue wait.
- **Settings**: App settings stored in SQLite, plus dedicated Settings pages for Jobs, Metrics, Statistics.
- **Repo status badge**: Header shows whether `origin/main` is ahead of the local repo.
- **Hello World addon**: Full UI and backend demo with job enqueue, scheduler controls, and worker simulator.

## Core Runtime
- **Backend**: FastAPI app that mounts core system routes and addon routers.
- **Frontend**: React app with core pages and dynamically loaded addon routes/links.
- **Addon discovery**: Core scans `addons/*/backend/addon.py`, validates each addon, and exposes metadata and errors.

### Addon Contracts
- Backend entrypoint: `addons/<id>/backend/addon.py` exporting `addon` (`AddonMeta` + `router`).
- Frontend entrypoint: `addons/<id>/frontend/index.ts` exporting `meta`, `routes`, and `navItem`.

### Addon Registry Endpoints
- `GET /api/addons` list addon metadata.
- `GET /api/addons/errors` addon load errors without blocking boot.

## Scheduler (Pull-Based Leasing)
- Priority queues: `high`, `normal`, `low`, `background`.
- Leases: workers request leases and receive a job + capacity allocation.
- Heartbeats: leases expire if heartbeats stop.
- Idempotency: optional `idempotency_key` prevents duplicate jobs.
- **Unique jobs**: `unique=true` prevents a worker from holding multiple active leases.

### Scheduler Endpoints
- `POST /api/system/scheduler/jobs` submit a job.
- `POST /api/system/scheduler/leases/request` request a lease.
- `POST /api/system/scheduler/leases/{lease_id}/heartbeat` extend a lease.
- `POST /api/system/scheduler/leases/{lease_id}/complete` complete a lease.
- `GET /api/system/scheduler/status` snapshot + queue depths.
- `GET /api/system/scheduler/jobs` job list (live in-memory).

## Job History (SQLite)
- Non-queued jobs are recorded into SQLite (leased/running/completed/failed/expired).
- Retention: **30 days** (auto-cleaned daily).
- Manual cleanup endpoint available.
- Metrics include success rate and average queue wait.

### History Endpoints
- `GET /api/system/scheduler/history/stats?days=30`
- `POST /api/system/scheduler/history/cleanup?days=30`

## System Metrics
- System stats sampling + API metrics aggregation drive scheduler busy rating.
- Stats snapshots saved to `data/system_stats.sqlite3`.

### Metrics Endpoint
- `GET /api/system/stats/current`

## App Settings (SQLite)
Simple key/value settings stored in SQLite, used by the Settings page.

### Settings Endpoints
- `GET /api/system/settings`
- `GET /api/system/settings/{key}`
- `PUT /api/system/settings/{key}`

## Repo Status (Header Badge)
Backend checks `HEAD` vs `origin/main` and exposes:
- `GET /api/system/repo/status`

Frontend shows “Update available” / “Up to date” / “Repo status unavailable”.

## Frontend Pages
- `/settings` — App settings (stored in SQLite).
- `/settings/jobs` — Live scheduler jobs + filters.
- `/settings/metrics` — System metrics + job summary (queued/leased).
- `/settings/statistics` — Job history stats by addon.
- `/addons` — Addon cards with enable/disable and open links.

## Hello World Addon
Demonstrates core addon features:
- Backend status endpoint: `/api/addons/hello_world/status`
- Job enqueue + burst enqueue
- Unique job flag
- Scheduler lease acquisition controls
- Worker simulator (start/stop/status)
- CPU burn simulation tied to requested units (target utilization)

### Worker Simulator
- Starts a simple in-app worker loop that requests leases and executes handlers.
- Adds a 2s “setup” delay before processing a job.
- Burns CPU on lease according to units and job duration.

## Repo Layout (Functional)
- `backend/app/main.py` — core wiring (scheduler, stats, settings, repo status).
- `backend/app/system/` — scheduler, stats, history, settings.
- `backend/app/addons/` — addon discovery and registry.
- `frontend/src/core/` — layout, routing, addon loader, settings pages.
- `addons/` — addon packages (backend + frontend + manifest).

## Notes
- Scheduler live state is in-memory; history is persisted to SQLite.
- If `origin/main` is unreachable, repo status will show as unavailable.

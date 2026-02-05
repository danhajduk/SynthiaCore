# SynthiaCore

SynthiaCore is a modular platform built around a Core + Addons architecture. Core provides the runtime, shared APIs, and system services; addons deliver feature-specific backend routes and frontend pages that can be added or removed independently.

## What It Does

### Core Runtime
- FastAPI backend that hosts core system APIs and dynamically mounts addon routers.
- React frontend that renders core pages and auto-loads addon routes and nav items.
- Addon discovery and registry: Core scans `addons/*/backend/addon.py`, validates each addon, and exposes a canonical list plus error diagnostics.

### Addon System (Backend + Frontend)
- Backend contract: Each addon exports an `addon` object from `addons/<id>/backend/addon.py` that includes `meta` (id, name, version, description) and `router` (FastAPI router).
- Frontend contract: Each addon exports from `addons/<id>/frontend/index.ts` (TSX allowed) the `meta`, `routes`, and `navItem` objects.
- Dynamic wiring: backend routes mount under `/api/addons/<id>`, and frontend routes are loaded via Vite glob import from `frontend/src/addons/*/index.ts` after sync.

Addon registry endpoints:
- `GET /api/addons` list addon metadata.
- `GET /api/addons/errors` list addon load errors without blocking boot.

### System Scheduler (Pull-Based Leasing)
SynthiaCore includes a built-in capacity-aware job scheduler designed for distributed workers.

- Queueing with priorities: `high`, `normal`, `low`, `background`.
- Lease-based execution: workers request leases and receive a job plus capacity allocation.
- Heartbeat and expiry: leases expire if workers stop heartbeating.
- Idempotent submission: optional `idempotency_key` prevents duplicate jobs.
- Capacity gating: availability is derived from system stats and API metrics.

Key scheduler endpoints:
- `POST /api/system/scheduler/jobs` submit a job.
- `POST /api/system/scheduler/leases/request` request a lease.
- `POST /api/system/scheduler/leases/{lease_id}/heartbeat` extend a lease.
- `POST /api/system/scheduler/leases/{lease_id}/complete` finish a lease.
- `GET /api/system/scheduler/status` system snapshot and queue depths.

### System Stats + Busy Rating
Core continuously samples system health and API performance to drive scheduling decisions.

- System stats: CPU, memory, load, disk, network.
- API metrics: request rates, p95 latency, error rate, inflight.
- Busy rating: a 0-10 score computed from system and API signals.
- Persistence: 1-minute snapshots stored in SQLite at `data/system_stats.sqlite3`.

Key system endpoint:
- `GET /api/system/stats/current` returns the latest cached snapshot.

### Admin Reload Endpoint
An admin route can trigger a systemd user service to reload or update the app.

- `POST /api/admin/reload` (requires `SYNTHIA_ADMIN_TOKEN` header).
- `GET /api/admin/reload/status` returns the last updater log tail.

## Repo Structure (Functional Overview)
- `backend/app/main.py` wires core APIs, scheduler, stats sampler, and addon registry.
- `backend/app/addons/` handles addon discovery, validation, and registration.
- `backend/app/system/` hosts scheduler, stats collection, and metrics.
- `frontend/src/core/` handles layout, routing, and addon loading.
- `addons/` contains feature packs (backend + frontend + manifest).

## Contracts and Guardrails
- Addon folder name must match addon `id`.
- Backend entrypoint is always `backend/addon.py`.
- Frontend entrypoint is `frontend/index.ts` (TSX allowed).
- Core never imports addon code directly; it only discovers and mounts.

## Example Addon
The repo includes `addons/hello_world` which demonstrates:
- A backend route at `/api/addons/hello_world/status`.
- A frontend page registered under `/addons/hello_world`.
- Addon metadata surfaced via `/api/addons`.

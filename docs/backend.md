# Backend Documentation

Last Updated: 2026-03-07 15:42 US/Pacific

## Overview

Backend is a FastAPI application assembled in `backend/app/main.py`.
It mounts core routers, addon routers, and store/scheduler/auth subsystems.

## Application Structure

- `app/main.py`: app factory, middleware, router wiring, background tasks
- `app/api/*`: top-level routers (system, admin, addon registry/install)
- `app/system/*`: scheduler, stats, auth, users, policy, telemetry, mqtt, services, runtime aggregation
- `app/store/*`: catalog/store lifecycle, source management, install/update/uninstall
- `app/addons/*`: discovery, registry, proxy, install sessions
- `synthia_supervisor/*`: standalone service reconciler (separate process)

## Router Groups (Mounted)

- `/api`:
  - health
  - core addon APIs (`/addons`, `/addons/errors`, enable)
  - admin session/reload
  - addon registry/install flows
- `/api/system`:
  - stats/current
  - settings
  - mqtt controls
  - repo status
  - standalone runtime aggregation (`/system/addons/runtime*`, admin-protected)
- `/api/system/scheduler`:
  - job submit, lease request/heartbeat/complete/report/revoke
  - queue endpoints and history endpoints
- `/api/auth`:
  - service-token issue/rotate
- `/api/policy`:
  - grants and revocations
- `/api/telemetry`:
  - usage ingest and stats
- `/api/services`:
  - service resolution
- `/api/store`:
  - schema, catalog, sources, install/update/uninstall, status, diagnostics, audit

## Background Behaviors

Started in backend startup event:
- Fast stats sampler
- API metrics sampler
- minute-level stats writer
- scheduler history cleanup loop
- addon health poll loop
- MQTT manager start (config controlled)

## Persistence and State

Backend uses mixed persistence:
- SQLite stores (settings/users/scheduler history/telemetry/stats/store audit)
- JSON files (install state, policy files, registry, store source metadata)

## Integration Points

- Store -> supervisor integration:
  - Core stages `addon.tgz`
  - Core writes `desired.json`
  - Core runtime aggregation service merges `desired.json`, `runtime.json`, and Docker container metadata
  - Store status/diagnostics endpoints read runtime data through the same runtime aggregation service
- Scheduler -> stats integration:
  - engine metrics provider uses sampled system metrics and API metrics
- Auth/user integration:
  - admin session + seeded admin user + service token key store

## Not Developed

- Hot runtime addon backend reload in-process (`hot_loaded` remains false in store responses)
- Strong distributed coordination primitives for scheduler/supervisor
- Active addon HTTP health probing in runtime aggregation (`/api/addon/health`) is not developed

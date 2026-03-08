# Backend Documentation

Last Updated: 2026-03-07 21:45 US/Pacific

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
  - platform events (`/system/events`)
  - repo status
  - stack summary (`/stack/summary`) for Home dashboard health/connectivity/speed view
    - local-network connectivity probe uses `SYNTHIA_LOCAL_NETWORK_CHECK_HOST`, then `MQTT_HOST`, then `SYNTHIA_BACKEND_HOST`/`SYNTHIA_BACKEND_PORT` when earlier targets are unset
    - provides `samples.network_throughput` from `latest_stats.net.total_rate` when available
    - provides `samples.network_metrics` from `latest_stats.net.total` counters (`bytes`, `packets`, `errors`, `drops`)
    - provides `samples.internet_speed` from cached value only (request path does not trigger speedtest execution)
      - cache refresh runs in backend background loop every `SYNTHIA_SPEEDTEST_SAMPLE_SECONDS` (30m default)
      - active runners: `SYNTHIA_SPEEDTEST_CLI_BIN`, python module fallback, Ookla JSON mode
      - falls back to `source=passive_estimate` from live RX/TX throughput when cached active speed state is unavailable
  - standalone runtime aggregation (`/system/addons/runtime*`, admin-protected)
  - optional service health probing (`GET /api/addon/health`) through runtime aggregation
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
  - service registration (`POST /register`) with service-token scope enforcement
- `/api/store`:
  - schema, catalog, sources, install/update/uninstall, status, diagnostics, audit

## Background Behaviors

Started in backend startup event:
- Fast stats sampler
- API metrics sampler
- minute-level stats writer
- scheduler history cleanup loop
- addon health poll loop
- internet-speed sampler loop (30m default cadence)
- MQTT manager start (config controlled)
- platform event emission to in-memory queue + logs (+ MQTT topic publish when available)

## Persistence and State

Backend uses mixed persistence:
- SQLite stores (settings/users/scheduler history/telemetry/stats/store audit)
- JSON files (install state, policy files, registry, store source metadata)
- MQTT integration state file (`var/mqtt_integration_state.json` via `MQTT_INTEGRATION_STATE_DB`)
  - stores grant status and provisioning/revocation result metadata per addon
  - stores setup awareness fields (`requires_setup`, `setup_complete`, `setup_status`, `broker_mode`, `direct_mqtt_supported`, `setup_error`)
  - inspection endpoints expose full grant list, per-addon grant, and setup/broker/health summary with aggregated provisioning errors

## Integration Points

- Store -> supervisor integration:
  - Core stages `addon.tgz`
  - Core writes `desired.json`
  - Core runtime aggregation service merges `desired.json`, `runtime.json`, and Docker container metadata
  - Store status/diagnostics endpoints read runtime data through the same runtime aggregation service
- Scheduler -> stats integration:
  - engine metrics provider uses sampled system metrics and API metrics
- MQTT control-plane integration:
  - deterministic operations use HTTP control endpoints on Core and MQTT addon APIs
    - approval/provision/revoke/setup-state update
  - MQTT broker topics are used for async events/visibility (announce, health, retained core info), not primary control transactions
- Auth/user integration:
  - admin session + seeded admin user + service token key store
- Service registry integration:
  - `/api/services/register` writes service entries with fields `service_type`, `addon_id`, `endpoint`, `health`, `capabilities`
  - registration binds token subject to `addon_id` and stores addon-registry metadata association with each service entry

## Not Developed

- Hot runtime addon backend reload in-process (`hot_loaded` remains false in store responses)
- Strong distributed coordination primitives for scheduler/supervisor
- Health probing is optional and disabled by default (`SYNTHIA_RUNTIME_HEALTH_PROBE_ENABLED=false` by default)
- Probing requires a reachable published TCP port; addons without probe endpoint report health as `unknown`
- durable event store and replay API for platform events

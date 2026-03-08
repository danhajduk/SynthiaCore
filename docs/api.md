# API Documentation (Structure)

Last Updated: 2026-03-07 21:49 US/Pacific

## Conventions

- API is FastAPI-based and primarily mounted under `/api/*`
- Route groups are assembled in `backend/app/main.py`
- JSON request/response bodies and standard HTTP status codes are used

## Major Route Groups

- `/api/health`
- `/api/addons*` (core addon listing, enablement, registry, install sessions, proxy aliases)
- `/api/admin/*` (session + reload + users/admin registry)
- `/api/system/*` (stats/settings/mqtt/repo/runtime)
- `/api/system/stack/summary` (dashboard-oriented full-stack summary: subsystems, connectivity, sampled speed, derived reasons)
- `/api/system/events` (recent platform events)
- `/api/system/scheduler/*` (jobs/leases/history/queue/debug)
- `/api/auth/*` (service token operations)
- `/api/policy/*` (grants/revocations)
- `/api/telemetry/*` (usage ingestion and stats)
- `/api/services/*` (service resolver + service registration)
- `/api/store/*` (schema/catalog/sources/install/update/uninstall/status/diagnostics/audit)

## Auth Requirements (High Level)

- Admin-protected endpoints require admin session/token checks.
- Service-oriented endpoints require service token scope checks.
- `POST /api/store/uninstall` is admin-protected and used by the Addons page uninstall action.

Implemented service registration auth:
- `POST /api/services/register` requires service token audience `synthia-core`
- required scope: `services.register`
- token subject (`sub`) must match `addon_id` in request
- Public/read endpoints remain accessible without admin privilege where designed.

Implemented MQTT provisioning handshake APIs:
- `POST /api/system/mqtt/registrations/approve`
  - validates addon eligibility and topic scope contract
  - creates/updates approved grant state in Core persistence
- `POST /api/system/mqtt/registrations/{addon_id}/provision`
  - calls MQTT addon provisioning endpoint with approved scopes, HA mode, and access profile
  - auth: admin session/token or service token (`aud=synthia-core`, scope `mqtt.provision`)
- `POST /api/system/mqtt/registrations/{addon_id}/revoke`
  - calls MQTT addon revoke endpoint and updates grant status
  - auth: admin session/token or service token (`aud=synthia-core`, scope `mqtt.revoke`)
- `GET /api/system/mqtt/grants`
- `GET /api/system/mqtt/grants/{addon_id}`
- `GET /api/system/mqtt/setup-summary`
  - exposes setup state and broker capability summary for operators/UI

Implemented admin-protected runtime endpoints:
- `GET /api/system/addons/runtime`
- `GET /api/system/addons/runtime/{addon_id}`

Implemented dashboard summary endpoint:
- `GET /api/system/stack/summary`
  - public/read endpoint used by Home dashboard
  - includes:
    - `status`: overall state + concise reasons
    - `subsystems`: core/supervisor/mqtt/scheduler/workers/addons
    - `connectivity`: local network + internet state
      - local network probe target precedence: `SYNTHIA_LOCAL_NETWORK_CHECK_HOST` -> `MQTT_HOST` -> `SYNTHIA_BACKEND_HOST` (with `SYNTHIA_BACKEND_PORT`, default `9001`) -> `not_configured`
    - `samples.internet_speed`: cached active speed sample only; `/stack/summary` never starts a new speedtest run
      - backend refreshes speed cache in startup background loop every `SYNTHIA_SPEEDTEST_SAMPLE_SECONDS` (default 1800 seconds / 30 minutes)
      - active runners supported: `SYNTHIA_SPEEDTEST_CLI_BIN`, python module fallback `python -m speedtest`, Ookla `speedtest --format=json`
      - when active speedtest is unavailable but throughput exists, backend returns `source=passive_estimate`
    - `samples.network_throughput`: live host RX/TX throughput sample from system stats (`rx_Bps`, `tx_Bps`)
    - `samples.network_metrics`: host cumulative network counters (`bytes_*`, `packets_*`, `err*`, `drop*`)
  - missing capability semantics may return `unknown`, `unavailable`, or `warming_up`

Runtime health model (implemented in runtime payload):
- `runtime_state`: container/process runtime state (`running|stopped|error|unknown`)
- `health_status`: service health state (`healthy|unhealthy|unknown`)
- runtime aggregation may call addon endpoint `GET /api/addon/health` when probe is enabled and a published TCP port exists
- runtime health probing is optional and disabled by default (`SYNTHIA_RUNTIME_HEALTH_PROBE_ENABLED`)

Implemented uninstall behavior boundary:
- `POST /api/store/uninstall` removes installed addon directory content managed by store lifecycle.
- Standalone service runtime cleanup is not currently automated via this endpoint.

## Service Discovery API

Implemented:
- `GET /api/services/resolve?capability={capability}`
  - resolution order: local loaded addon registry -> registered remote addon registry -> service catalog store
- `POST /api/services/register`
  - body fields:
    - `service_type`
    - `addon_id`
    - `endpoint`
    - `health`
    - `capabilities[]`
  - persisted metadata includes addon registry association (`name`, `version`, `enabled`, local/remote flags)

## Platform Events API

Implemented:
- `GET /api/system/events`
  - returns recent in-memory platform events
  - supports filters: `event_type`, `source`, `limit`
- Current emitted event types:
  - `addon_installed`
  - `addon_started`
  - `addon_failed`
  - `addon_updated`
  - `job_completed`
  - `service_registered`

Not developed:
- durable event persistence across backend restarts
- subscription/streaming API (SSE/WebSocket)
- event delivery retries and dead-letter queue semantics

## Error Format

Implemented:
- Endpoint-specific `detail` payloads for validation and operational diagnostics.
- Store endpoints include structured remediation hints for known failure classes.

## Versioning

Implemented:
- App version appears in FastAPI app metadata (`0.1.0` in backend factory).

Not developed:
- Formal multi-version API versioning strategy across major revisions.

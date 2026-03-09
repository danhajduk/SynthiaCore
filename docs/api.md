# API Documentation (Structure)

Last Updated: 2026-03-08 16:22 US/Pacific

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
- `GET /api/system/mqtt/status`
  - returns MQTT connection/runtime status and subscription list
- `POST /api/system/mqtt/test`
  - publishes a test payload to MQTT for connectivity diagnostics
- `POST /api/system/mqtt/restart`
  - restarts MQTT client connection and returns updated status
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
  - exposes setup state, broker capability summary, MQTT health summary, and aggregated `last_provisioning_errors` for operators/UI
- `POST /api/system/mqtt/setup-state`
  - updates Core-side MQTT setup awareness (`requires_setup`, `setup_complete`, `setup_status`, `broker_mode`, `direct_mqtt_supported`, `setup_error`)
  - auth: admin session/token or service token (`aud=synthia-core`, scope `mqtt.setup.write`, subject `mqtt`)
  - provisioning endpoints are gated until setup is ready when setup is required

MQTT control-plane rule (implemented contract):
- Core uses HTTP APIs for deterministic control transactions (registration approval, provisioning, revocation, setup-state updates, admin actions).
- MQTT topics are treated as async/event transport only (announce, health, telemetry, retained info), not as the primary control transaction channel.

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
- `POST /api/store/uninstall` now performs standalone cleanup when a service exists:
  - writes `desired_state=stopped` to standalone desired intent when available
  - performs best-effort `docker compose down --remove-orphans` using standalone project metadata
  - performs best-effort docker image cleanup for compose image IDs (`docker compose images -q` -> `docker image rm -f`)
  - removes standalone service files under `SYNTHIA_ADDONS_DIR/services/{addon_id}`

Implemented standalone UI status fields in Store status/install/update payloads:

- `ui_reachable`: backend-computed readiness for standalone addon UI
- `ui_redirect_target`: frontend route target (`/addons/{addon_id}`) when reachable
- `ui_embed_target`: backend proxy path used by iframe embed (`/ui/addons/{addon_id}`)
- `ui_reason`: backend readiness reason (`ready`, `runtime_unavailable`, `runtime_not_running`, `no_published_ports`, `health_unhealthy`)

Implemented standalone desired rewrite behavior:

- `POST /api/store/standalone/update` rewrites desired intent and always sets `force_rebuild=true` so supervisor rebuild/recreate is triggered on the next reconcile cycle.

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

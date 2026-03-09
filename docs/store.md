# Store and Catalog Documentation

Last Updated: 2026-03-08 16:33 US/Pacific

## Scope

Store subsystem manages catalog sources, schema exposure, install/update/uninstall flows, status and diagnostics.

## Main Modules

- `app/store/router.py`: API contract and orchestration
- `catalog.py`: source refresh/cache and catalog reading
- `lifecycle.py`: install/update/uninstall operations
- `extract.py`: package extraction/validation
- `resolver.py`: compatibility checks
- `audit.py`: store audit persistence
- `standalone_desired.py`, `standalone_paths.py`: standalone runtime intent/path utilities

## Catalog and Sources

Implemented:
- source CRUD and refresh endpoints
- cache metadata per source in runtime store cache paths
- source validate endpoint for schema/version checks

## Install Pipeline

Implemented:
- artifact retrieval and staging
- compatibility checks
- install/update/uninstall endpoint flows
- standalone install mode writes `desired.json` and stages `addon.tgz`
- standalone desired update endpoint (`POST /api/store/standalone/update`) rewrites `desired.json` in place for installed standalone services and always sets `force_rebuild=true`
- standalone release manifests may define `runtime_defaults` (`ports`, `bind_localhost`); Core resolves runtime defaults from extracted artifact `manifest.json` first and falls back to catalog/normalized manifest metadata when unavailable
- standalone runtime overrides support optional `cpu` and `memory` values for desired runtime intent
- standalone uninstall path now performs desired-state stop intent, best-effort compose teardown, and standalone service directory removal
- standalone uninstall path now also performs best-effort compose image cleanup (`docker compose images -q` + `docker image rm -f`) before service directory removal
- status/diagnostic endpoints read runtime state and summarize errors
- standalone install/status payloads expose UI embed contract fields (`ui_reachable`, `ui_redirect_target`, `ui_embed_target`, `ui_reason`)
- frontend install success flow may auto-redirect to addon UI route (`/addons/{addon_id}`) when `ui_reachable=true`; otherwise it stays in store with fallback guidance
- diagnostics expose standalone retention policy and retained/prunable version lists

## File Contracts (Store vs Supervisor)

### `manifest.json` (addon-provided artifact file)

Store expectations:
- Local embedded install path validates extracted addon layout with:
  - required `manifest.json`
  - required `backend/addon.py`
  - `manifest.id` must match target addon id
- Machine-readable artifact manifest schema reference: `docs/addon-manifest.schema.json`.
- Catalog install path builds/validates `ReleaseManifest` from catalog release/manifest data.
- `ReleaseManifest` supports optional `runtime_defaults`:
  - `ports[]` (`host`, `container`, `proto`, optional `purpose`)
  - `bind_localhost`

Store ownership:
- Store reads and validates manifest inputs.
- Store does not write addon `manifest.json`.

### `desired.json` (Core-owned runtime intent)

Store expectations/behavior:
- Written by Store for `install_mode=standalone_service`.
- Validated against `DesiredStatePayload` schema before write.
- Machine-readable reference schema: `docs/desired.schema.json`.
- Key required fields written:
  - `ssap_version`, `addon_id`, `mode`, `desired_state`, `desired_revision`, `force_rebuild`, `enabled_docker_groups`, `channel`
  - `install_source` (`type`, `catalog_id`, `release`)
  - `runtime` (`project_name`, `network`, `ports`, `bind_localhost`, optional `cpu`, `memory`)
  - `config.env`

Runtime precedence used by Store when writing `desired.json`:
- `runtime_overrides` request fields win.
- then extracted addon `manifest.json` `runtime_defaults` (ports/bind_localhost).
- then catalog/normalized `ReleaseManifest.runtime_defaults`.
- then Store fallbacks (`ports=[]`, `bind_localhost=true`, default network/project name).

Desired-state handoff behavior:
- Store writes `desired.json` by atomic replace (`write_desired_state_atomic`).
- There is no direct Store -> Supervisor notify API.
- Supervisor picks up desired changes on its next poll cycle.
- Store writes a `desired_revision` marker so supervisor can detect desired changes deterministically.
- Same-version compose-affecting desired changes are applied by supervisor via compose-file regeneration/reconcile.
- `enabled_docker_groups` values are validated against addon-declared `manifest.json` `docker_groups[]`; unknown groups are rejected.

### `runtime.json` (Supervisor-owned runtime state)

Store expectations/behavior:
- Store does not write runtime state.
- Store reads runtime snapshots (via runtime aggregation service) for status/diagnostics.
- During standalone uninstall, Store may read state for compose target selection but runtime file lifecycle remains supervisor-owned.

## Standalone UI Embed Contract

Implemented contract between Store API and frontend `AddonFrame` route:

- `ui_reachable`:
  - `true` only when standalone runtime state is `running`, health is not unhealthy, and published ports are present.
- `ui_redirect_target`:
  - set to `/addons/{addon_id}` when `ui_reachable=true`; otherwise `null`.
- `ui_embed_target`:
  - backend proxy path for iframe embedding, currently `/ui/addons/{addon_id}`.
- `ui_reason`:
  - readiness/fallback reason (`ready`, `runtime_unavailable`, `runtime_not_running`, `no_published_ports`, `health_unhealthy`).

Frontend behavior:

- install flow uses `ui_reachable` + `ui_redirect_target` for post-install navigation
- `AddonFrame` probes `/api/store/status/{addon_id}` and:
  - shows loading while readiness is pending
  - renders iframe using `ui_embed_target` once reachable and addon is loaded in Core
  - falls back to direct `standalone_runtime.published_ports` host-port URL when runtime is running but addon is not loaded in Core yet
  - renders fallback message when runtime enters error state or readiness times out

## Development Policy

Checksum and signature verification are intentionally disabled during development.
Verification utility paths exist but enforcement is currently bypassed in active store/supervisor flows.

## Not Developed

- Production-grade trust enforcement pipeline (strict verification required mode)
- Full zero-downtime addon rollout orchestration

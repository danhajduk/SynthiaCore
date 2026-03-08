# SynthiaCore

SynthiaCore is a Core + Addons platform with a built-in scheduler, system metrics, and a frontend that auto-loads addons. This README reflects the current functionality in the repo.

## Highlights
- **Core runtime**: FastAPI backend + React frontend with addon discovery and dynamic routing.
- **Scheduler**: Pull-based leases, capacity-aware, priority queues, idempotent jobs, unique job flag.
- **History + stats**: SQLite-backed job history (30-day retention), stats by addon, success rate, queue wait.
- **Settings**: Structured control-plane Settings page (General/Platform/Connectivity/Addon Registry/Security/Developer tools) plus dedicated Jobs, Metrics, Statistics pages.
- **Repo status badge**: Header shows whether `origin/main` is ahead of the local repo.
- **Hello World addon**: Full UI and backend demo with job enqueue, scheduler controls, and worker simulator.
- **Distributed addon policy baseline**: `docs/distributed_addons/README.md` maps current implementation to policy docs and tracked gap tasks.

## Core Runtime
- **Backend**: FastAPI app that mounts core system routes and addon routers.
- **Frontend**: React app with core pages and dynamically loaded addon routes/links.
- **Addon discovery**: Core scans `addons/*/backend/addon.py`, validates each addon, and exposes metadata and errors.

### Addon Contracts
- Backend entrypoint: `addons/<id>/backend/addon.py` exporting `addon` (`AddonMeta` + `router`).
- Frontend entrypoint: `addons/<id>/frontend/index.ts` exporting `meta`, `routes`, and `navItem`.
- Backend discovery ignores hidden addon folders (for example `.store_backup` and `.store_staging`) to avoid runtime store workdir noise.

### Addon Registry Endpoints
- `GET /api/addons` list addon metadata.
- `GET /api/addons/errors` addon load errors without blocking boot.
- `GET /api/addons/registry` list registered distributed addons.
- `GET /api/addons/registry/{addon_id}` get one registered addon.
- `POST /api/addons/registry/{addon_id}/register` (admin auth required) upsert base URL and refresh remote addon meta/capabilities.
- `POST /api/addons/registry/{addon_id}/configure` (admin auth required) forward config payload to addon `/api/addon/config`.
- `POST /api/addons/registry/{addon_id}/verify` (admin auth required) probe addon `/api/addon/health` and update registry health fields.

### Addon Install Session Endpoints
- `POST /api/addons/install/start` (admin auth required) create install session in `pending_permissions`.
- `POST /api/addons/install/{session_id}/permissions/approve` (admin auth required) move to `pending_deployment`.
- `POST /api/addons/install/{session_id}/deployment/select` (admin auth required) persist `external|embedded` deployment choice.
- `POST /api/addons/install/{session_id}/configure` (admin auth required) forward config to registered addon and mark session configured.
- `POST /api/addons/install/{session_id}/verify` (admin auth required) run addon health check and mark session verified/error.
- `GET /api/addons/install/{session_id}` read current session state.
- MQTT announce events on `synthia/addons/{addon_id}/announce` auto-advance matching sessions from `pending_deployment` to `discovered`.

### Addon Store Schema Endpoint (Phase 1)
- `GET /api/store/schema` returns JSON schemas for `AddonManifest`, `ReleaseManifest`, `CompatibilitySpec`, and `SignatureBlock`.
- `ReleaseManifest.compatibility` is canonical for core-version/dependency/conflict constraints.
- Legacy top-level compatibility fields are soft-deprecated and adapter-backed for backward compatibility.
- `ReleaseManifest.version` accepts semver and semver-with-suffix tags (for example `0.1.7d`) for catalog release compatibility.

### Addon Store Signing (Phase 1)
- `backend/app/store/signing.py` enforces pre-enable SHA256 checksum validation.

### Addon Store Resolver (Phase 1)
- `backend/app/store/resolver.py` validates core-version compatibility, dependencies, and conflicts.
- Resolution is deterministic (sorted dependency/conflict sets) and blocks on validation failures only (no auto-download path).

### Store Module Layout
- `backend/app/store/router.py` now focuses on endpoint wiring.
- `backend/app/store/lifecycle.py` contains install/update/uninstall and retention cleanup logic.
- `backend/app/store/extract.py` contains safe archive extraction and layout validation.
- `backend/app/store/audit.py` owns `store_audit_log` persistence.

### Addon Store Lifecycle APIs (Phase 1)
- `GET /api/store/catalog` (stub in Task 5, backed by catalog module in Task 6)
- `POST /api/store/install` (admin auth required; supports local package install or catalog install by `source_id` + `addon_id` + optional `version`)
- `POST /api/store/update` (admin auth required)
- `POST /api/store/uninstall` (admin auth required)
- `GET /api/store/status/{addon_id}`
- `GET /api/store/status/summary`
- `GET /api/store/status/{addon_id}/diagnostics`
- Store lifecycle audit events are persisted to SQLite table `store_audit_log` (`STORE_AUDIT_DB`, default `var/store_audit.db`).
- Install/update responses expose `registry_loaded` (present in current registry snapshot) and `hot_loaded` (currently always `false` until runtime hot-reload support exists).
- Internal lifecycle pipeline keeps parsed `installed_manifest` metadata for future validation/UI enrichments; it is not persisted as a separate DB row in Phase 1.
- Store workdir cleanup runs at install/update start:
  - `STORE_BACKUP_RETENTION` (default `3`)
  - `STORE_STAGING_TTL_MINUTES` (default `60`)
- Admin audit endpoint:
  - `GET /api/store/admin/audit?addon_id=&action=&status=&from_ts=&to_ts=&page=&page_size=` (admin auth required)

Store sources endpoints:
- `GET /api/store/sources`
- `POST /api/store/sources` (admin auth required)
- `DELETE /api/store/sources/{id}` (admin auth required)
- `POST /api/store/sources/{id}/refresh` (admin auth required)
- `GET /api/store/sources/{id}/validate` (admin auth required; validates cached catalog schema/release versions without install)

Catalog cache behavior (Phase 2):
- Official source uses `https://raw.githubusercontent.com/danhajduk/Synthia-Addon-Catalog/main`; legacy `/master` official configs are auto-migrated to `/main` at startup.
- Source refresh fetches `catalog/v1/index.json`, `index.json.sig`, `publishers.json`, `publishers.json.sig`.
- Official source refresh now retries the alternate branch (`main` <-> `master`) on `catalog_http_error:404` before failing.
- Cache path: `runtime/store/cache/<source_id>/` with `metadata.json`.
- Store source/cache runtime state (`backend/var/store_sources.json`, `runtime/store/cache/`) is local-only and ignored by git.
- Catalog signature verification is disabled during source refresh.
- Refresh metadata exposes `catalog_integrity_mode=signature_disabled`.
- `GET /api/store/catalog` now reads cached catalog content (source-aware) and returns structured status fields:
  - `status`, `source_id`, `last_success_at`, `last_error_at`, `last_error_message`.
  - `installed` map payload: `{ [addon_id]: { version, installed_at } }`
  - when cache uses `addons[]` entries, backend normalizes `addon_id -> id` and includes `package_profile`, `version`, `publisher_id`, `publisher_display_name`, `release_count`, and `releases` for richer UI metadata.
  - channel catalogs are normalized from `channels.<name>[]` and wrapped `channels.<name>.releases[]` entries so UI release details remain populated.
- Catalog install flow:
  - resolves release from cached catalog by addon/version (accepts both `id` and `addon_id` source keys; defaults to latest compatible release),
  - accepts channel release entries from both `channels.<name>[]` and wrapped `channels.<name>.releases[]` schemas,
  - on artifact download `404`, backend performs one source refresh + re-resolve retry before failing install,
  - if artifact `404` persists after retry, install returns `409` with `catalog_artifact_unavailable` including source and artifact URL details,
  - checksum metadata (`sha256`, `checksum`) is accepted as informational install metadata only (not enforced),
  - package/layout consistency failures return structured diagnostics: `catalog_package_layout_invalid` for generic embedded entrypoint issues, `catalog_profile_layout_mismatch` when catalog metadata says `embedded_addon` but artifact layout is service-style (`app/main.py`), and `catalog_package_profile_unsupported` with `remediation_path=standalone_deploy_register` when standalone packages are intentionally unsupported by embedded install flow,
  - compatibility checks use `SYNTHIA_CORE_VERSION` (default `0.1.0` if unset); set this in `scripts/synthia.env` to match deployed core semver,
  - when no compatible release exists, install returns `409` with `catalog_no_compatible_release` plus resolver reasons (for example core-version minimum mismatch),
  - invalid catalog release versions now return `400` with `remediation_path=catalog_release_version_format` for direct UI/operator guidance,
  - derives missing `publisher_id` from `publisher_key_id` when catalog releases omit explicit publisher id,
  - accepts release artifact metadata in either top-level (`artifact_url`/`url`/`download_url`) or nested (`artifact.url`) forms,
  - supports both `.zip` and tar-based addon artifacts (including `.tgz`) for catalog installs,
  - downloads artifact with catalog client redirect/timeout/size protections,
  - skips checksum and signature verification during artifact install,
  - records source metadata used by `GET /api/store/status/{addon_id}`,
  - persists `last_install_error` debug context after catalog install failures (error code, source id, resolved base URL, artifact URL, remediation_path when available).

Store status response fields (Phase 2):
- `installed_version`
- `installed_from_source_id`
- `installed_resolved_base_url`
- `installed_release_url`
- `installed_sha256`
- `installed_at`
- `last_install_error` (or `null` after successful install)

Store incident runbook:
- `docs/addon-store/incident-runbook.md` covers `catalog_artifact_unavailable` triage/recovery.
- `scripts/validate-catalog-package-profile.sh <package_profile> <artifact_path>` enforces release profile/layout alignment before catalog publication.

Catalog query parameters:
- `q` free-text search over id/name/description/categories
- `category` category filter
- `featured` featured-only filter
- `sort` supports `recent`, `name`, fallback `id`
- `page`, `page_size` pagination
- Response includes `catalog_status` with `status`, `message`, and `last_successful_load` for operator visibility on catalog read/parse errors.

Store API request-level tests now cover success and failure paths for catalog/install/update/uninstall/status endpoints (`backend/tests/test_store_api_endpoints.py`).

## Scheduler (Pull-Based Leasing)
- Priority queues: `high`, `normal`, `low`, `background`.
- Leases: workers request leases and receive a job + capacity allocation.
- Heartbeats: leases expire if heartbeats stop.
- Idempotency: optional `idempotency_key` prevents duplicate jobs.
- **Unique jobs**: `unique=true` prevents a worker from holding multiple active leases.
- Debug scheduler surfaces are gated by `SCHEDULER_DEBUG_ENABLED` (default disabled).

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

## Policy Grants + Revocations
- `GET /api/policy/grants?service=<name>` polling fallback list for grants.
- `POST /api/policy/grants` upserts a grant and publishes retained MQTT update on `synthia/policy/grants/{service}`.
- `GET /api/policy/revocations` polling fallback list for revocations.
- `POST /api/policy/revocations` upserts a revocation and publishes retained MQTT update on `synthia/policy/revocations/{id}`.

Grant model:
- `grant_id`, `consumer_addon_id`, `service`, `period_start`, `period_end`, `limits`, `status`

## Usage Telemetry
- `POST /api/telemetry/usage` ingests usage reports from service addons.
- `GET /api/telemetry/usage` returns persisted usage history with filters (`service`, `consumer_addon_id`, `grant_id`) and `limit`.
- `GET /api/telemetry/usage/stats?days=30` returns aggregate totals and grouped rollups by service, consumer, and grant.
- Telemetry ingestion requires service JWT role/scope (`aud=synthia-core`, scope `telemetry.write`).

## Security Baseline
- Roles are separated as:
  - `admin`: privileged write operations (`/api/system/settings/*` PUT, policy grant/revocation updates, token issuance)
  - `service`: service-to-core operations using JWT bearer tokens (telemetry usage ingest)
  - `guest`: read-only/public endpoints
- Admin auth for privileged endpoints supports:
  - `X-Admin-Token` header (legacy/dev compatibility)
  - HttpOnly signed cookie session via:
    - `POST /api/admin/session/login` with `{ "token": "..." }`
    - `POST /api/admin/session/login-user` with `{ "username": "...", "password": "..." }` (admin-role user required)
    - `GET /api/admin/session/status`
    - `POST /api/admin/session/logout`
- Admin user-management endpoints:
  - `GET /api/admin/users`
  - `POST /api/admin/users`
  - `DELETE /api/admin/users/{username}`
- Admin users are seeded/enforced from env at startup:
  - `SYNTHIA_ADMIN_USERNAME` (default `admin`)
  - `SYNTHIA_ADMIN_PASSWORD` (fallback: `SYNTHIA_ADMIN_TOKEN`)
- Secret redaction is applied to outbound MQTT payloads before publish.
- Audit log records are written for:
  - grant changes
  - revocation changes
  - privileged config updates
- Registered addon `base_url` targets produce TLS warnings for non-HTTPS non-localhost URLs (`tls_warning` field).
- MQTT listener controls:
  - `MQTT_LISTENER_ENABLED` (default `true`) toggles Core MQTT listener startup without affecting backend boot.

## Repo Status (Header Badge)
Backend checks `HEAD` vs `origin/main` and exposes:
- `GET /api/system/repo/status`

Frontend shows “Update available” / “Up to date” / “Repo status unavailable”.

## Frontend Pages
- Guest access is limited to `/` (Home). Non-home routes redirect to `/` until an admin session is active.
- Home page includes admin username/password sign-in and sign-out controls backed by `/api/admin/session/*` cookie-session endpoints.
- `/store` — Addon Store catalog page with refresh, client-side search, install actions, channel-aware release detail rendering, package-profile field on addon cards, profile-mismatch action cards, expandable install diagnostics, display-name-first publisher rendering, and quick-action remediation links to docs for version/profile issues.
- `/store` status card now includes install-failure triage summary (`tracked_addons`, `addons_with_errors`, top failure code) from `/api/store/status/summary`.
- `/addons` — Addons inventory plus distributed install wizard (install session start, permissions, deployment choice, discovery polling, configure, verify, and UI link).
- `/settings` — Structured control-plane settings page.
- `/settings/jobs` — Live scheduler jobs + filters.
- `/settings/metrics` — System metrics + job summary (queued/leased).
- `/settings/statistics` — Job history stats by addon.
- `/addons` — Addon cards with enable/disable and open links.
- `/settings` includes:
  - General settings (`app.name`, `app.maintenance_mode`, theme selection)
  - Platform and connectivity summaries from `/api/system/stack/summary` and `/api/system/mqtt/status`
  - addon registry management (`/api/admin/addons/registry`)
  - user management CRUD (`/api/admin/users`)
  - collapsible developer diagnostics (runtime reload and service resolver probe)
- `/addons` includes control-plane metadata fields (`base_url`, `capabilities`, `health`, `last_seen`, `auth_mode`, `tls_warning`).

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
- `frontend/src/theme/` — token-based theme CSS entrypoint, base/component primitives, and dark/light theme overrides.
- `frontend/src/theme/theme.ts` — runtime theme initialization and localStorage-backed theme selection helper.
- `addons/` — addon packages (backend + frontend + manifest).

## Notes
- Scheduler live state is in-memory; history is persisted to SQLite.
- If `origin/main` is unreachable, repo status will show as unavailable.
- Active planning source is `docs/ROADMAP.md`; legacy TODO docs are archived in `docs/archive/`.
- Service reload helper: `bash scripts/reload-all.sh` (reloads user units, restarts backend/frontend and optional dashboard/supervisor when installed, runs updater oneshot, prints status).
- Bootstrap installs user unit templates for backend, frontend, updater, and supervisor into `~/.config/systemd/user/`.
- Settings Metrics (`/settings/metrics`) now includes current backend/frontend/updater/supervisor user-unit status from `/api/system/stats/current`.
- Standalone-service SSAP helpers now include backend utilities for `desired.json` payload creation and atomic writes.
- SSAP desired-state utilities enforce validation for `ssap_version`, `mode`, `desired_state`, `channel`, and lowercase SHA-256 format.
- Catalog installs for `standalone_service` now stage verified artifacts under `SynthiaAddons/services/<addon_id>/versions/<version>/addon.tgz` (no container start from Core).
- Supervisor reconciliation runs extract, compose file generation, and `docker compose up` for standalone services.
- Supervisor only switches `current` to the new version after successful `docker compose up`, using rename-based atomic symlink replacement.
- On activation failure, supervisor runtime state includes rollback metadata (`previous_version`, `rollback_available`, `last_error`).
- Store status API (`/api/store/status/{addon_id}`) now reads standalone runtime state from `services/<addon_id>/runtime.json` and exposes `runtime_state`, `standalone_runtime`, and `runtime_path`.
- Store diagnostics API (`/api/store/status/{addon_id}/diagnostics`) exposes latest standalone runtime error context and a concise `last_error_summary` for compose/build failure triage.
- Store install/update responses now include SSAP metadata fields (`mode`, `desired_path`, `runtime_path`, `staged_artifact_path`, `runtime_state`, `registry_state`).
- Supervisor-generated compose defaults now enforce guardrails: `privileged: false`, `no-new-privileges`, dedicated `synthia_net`, and service token/env injection via env file; port publish bind defaults to localhost and can be widened with `runtime.bind_localhost=false`.
- Regression tests now cover standalone runtime status read paths (missing/valid/malformed), verification-failure stop behavior, and upgrade/rollback metadata transitions.
- Standalone smoke regression test `backend/tests/test_standalone_smoke_flow.py` covers install intent write, runtime status read, and addon health/UI proxy route reachability.
- Frontend global `style.css` root background/text now consume theme tokens to support runtime dark/light theme switching.
- Settings page now includes a persisted theme selector (Dark/Light) backed by `localStorage` and `document.documentElement.dataset.theme`.
- Legacy `frontend/src/style.css` globals were migrated into `frontend/src/theme/base.css`; theme CSS is now the single global styling source.
- Addon theme consumption contract is documented in `docs/theme.md` (shared CSS path, import usage, and token rules).
- Registry API route precedence is enforced so `/api/addons/registry/{id}/register` is handled by registry endpoints before addon proxy catch-all routing.
- Unified addon integration and registration reference is documented in `docs/addons.md`.
- Supervisor reconciliation now emits step-by-step logs (desired load, verify, extract, compose, start/stop); set `SYNTHIA_SUPERVISOR_LOG_LEVEL` (default `INFO`) for verbosity.
- SSAP operator lifecycle and troubleshooting runbook: `docs/addon-store/SSAP_operator_runbook.md`.
- Local operator config should stay untracked:
  - copy `scripts/synthia.env.example` to `scripts/synthia.env` for machine-specific values.
  - set `SYNTHIA_ADDONS_DIR` to override standalone-service state root; default now resolves to sibling `../SynthiaAddons` (outside repo), and external paths like `~/.local/share/synthia/SynthiaAddons` are also supported.
  - keep per-user systemd overrides under `~/.config/synthia/*.env` (already outside this repo).

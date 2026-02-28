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

### Addon Store Schema Endpoint (Phase 1)
- `GET /api/store/schema` returns JSON schemas for `AddonManifest`, `ReleaseManifest`, `CompatibilitySpec`, and `SignatureBlock`.
- `ReleaseManifest.compatibility` is canonical for core-version/dependency/conflict constraints.
- Legacy top-level compatibility fields are soft-deprecated and adapter-backed for backward compatibility.

### Addon Store Signing (Phase 1)
- `backend/app/store/signing.py` enforces pre-enable verification: SHA256 checksum + RSA signature validation.
- Verification fails closed with structured error payloads (`code`, `message`, `details`).

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
- `POST /api/store/install` (admin token required; supports local package install or catalog install by `source_id` + `addon_id` + optional `version`)
- `POST /api/store/update` (admin token required)
- `POST /api/store/uninstall` (admin token required)
- `GET /api/store/status/{addon_id}`
- Store lifecycle audit events are persisted to SQLite table `store_audit_log` (`STORE_AUDIT_DB`, default `var/store_audit.db`).
- Install/update responses expose `registry_loaded` (present in current registry snapshot) and `hot_loaded` (currently always `false` until runtime hot-reload support exists).
- Internal lifecycle pipeline keeps parsed `installed_manifest` metadata for future validation/UI enrichments; it is not persisted as a separate DB row in Phase 1.
- Store workdir cleanup runs at install/update start:
  - `STORE_BACKUP_RETENTION` (default `3`)
  - `STORE_STAGING_TTL_MINUTES` (default `60`)
- Admin audit endpoint:
  - `GET /api/store/admin/audit?addon_id=&action=&status=&page=&page_size=` (admin token required)

Store sources endpoints:
- `GET /api/store/sources`
- `POST /api/store/sources` (admin token required)
- `DELETE /api/store/sources/{id}` (admin token required)
- `POST /api/store/sources/{id}/refresh` (admin token required)

Catalog cache behavior (Phase 2):
- Source refresh fetches `catalog/v1/index.json`, `index.json.sig`, `publishers.json`, `publishers.json.sig`.
- Cache path: `runtime/store/cache/<source_id>/` with `metadata.json`.
- Catalog signatures are verified against configured store public key(s); refresh fails closed and keeps last-known-good cache on invalid/missing signatures.
- Catalog public key configuration:
  - `STORE_CATALOG_PUBLIC_KEYS_PATH` (default `var/store_catalog_public_keys.json`)
  - `STORE_CATALOG_PUBLIC_KEYS_JSON` (inline JSON override; supports multi-key rotation)
- `GET /api/store/catalog` now reads cached catalog content (source-aware) and returns structured status fields:
  - `status`, `source_id`, `last_success_at`, `last_error_at`, `last_error_message`.
- Catalog install flow:
  - resolves release from cached catalog by addon/version (defaults to latest compatible release),
  - downloads artifact with catalog client redirect/timeout/size protections,
  - enforces `release.publisher_key_id` lookup in cached `publishers.json` (must exist and be enabled),
  - enforces detached signature type support (`rsa-sha256` only),
  - verifies SHA256 + detached `release_sig` over artifact bytes before atomic install,
  - records source metadata used by `GET /api/store/status/{addon_id}`.

Store status response fields (Phase 2):
- `installed_version`
- `installed_from_source_id`
- `installed_release_url`
- `installed_sha256`
- `installed_at`

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
- Secret redaction is applied to outbound MQTT payloads before publish.
- Audit log records are written for:
  - grant changes
  - revocation changes
  - privileged config updates
- Registered addon `base_url` targets produce TLS warnings for non-HTTPS non-localhost URLs (`tls_warning` field).

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
- `/settings` also includes admin control-plane tools:
  - core reload controls
  - remote addon registry CRUD (`/api/admin/addons/registry`)
  - MQTT status view and service resolver probe
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
- `addons/` — addon packages (backend + frontend + manifest).

## Notes
- Scheduler live state is in-memory; history is persisted to SQLite.
- If `origin/main` is unreachable, repo status will show as unavailable.
- Active planning source is `docs/ROADMAP.md`; legacy TODO docs are archived in `docs/archive/`.

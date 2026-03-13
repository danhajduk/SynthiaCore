# Archived Root README

Archived from `/README.md` during the front-door documentation rewrite on 2026-03-12.

---

# SynthiaCore

SynthiaCore is a Core + Addons platform with a built-in scheduler, system metrics, and a frontend that auto-loads addons. This README reflects the current functionality in the repo.

## Documentation Source of Truth
- This `README.md` is a high-level overview.
- For implementation-level behavior, use:
  - `docs/document-index.md` (docs front door)
  - `docs/api-reference.md`
  - `docs/core-platform.md`
  - `docs/mqtt-platform.md`
- Policy/spec documents under `docs/Policies/` are design/reference material and may include planned behavior that is not implemented.

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
- Store artifact checksum/signature verification is currently disabled in install flow.
- `backend/app/store/signing.py` remains as compatibility/helper code and does not enforce install-time checks.

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

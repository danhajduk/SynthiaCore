# Synthia Supervisor Runtime Specification (Code-Verified)

Last Updated: 2026-03-08 16:16 US/Pacific

This document only describes behavior that is present in code today. Any missing capability is explicitly labeled **Not developed**.

## Documentation Contract

This document describes the **actual behavior implemented in code**.

If a capability, safeguard, validation rule, or runtime behavior is **not explicitly documented here as implemented**, it must be assumed to be **not developed / not guaranteed by the current supervisor implementation**.

Sections labeled **Not developed** represent intentionally missing functionality or areas planned for future implementation.

Code sources used:
- `backend/synthia_supervisor/main.py`
- `backend/synthia_supervisor/docker_compose.py`
- `backend/synthia_supervisor/models.py`
- `backend/synthia_supervisor/crypto.py`
- `backend/app/store/router.py`
- `backend/app/system/runtime/service.py`
- `backend/app/store/standalone_desired.py`
- `backend/app/store/standalone_paths.py`
- `backend/app/system/stats/service.py`
- `systemd/user/synthia-supervisor.service.in`
- `backend/tests/test_synthia_supervisor_main.py`
- `backend/tests/test_synthia_supervisor_compose.py`

## 1) Reconcile Timing Model

Implemented:
- Supervisor is polling-based (`while True` loop in `main.py`).
- Default poll interval is 5 seconds (`DEFAULT_INTERVAL_S=5`, overridable by `SYNTHIA_SUPERVISOR_INTERVAL_S`).
- Addons are reconciled sequentially (single loop over `services_dir.iterdir()` and synchronous `reconcile_one`).

Worst-case reaction delay (code-derived):
- `poll interval + time spent reconciling earlier addon directories in that loop iteration`.
- There is no parallel reconcile worker pool.

## 1.1) Reconcile Result and Post-Reconcile Hooks

Implemented:
- `reconcile_one(addon_dir)` returns a structured `ReconcileResult` (or `None` when `desired.json` is missing).
- `ReconcileResult` fields:
  - `addon_id`
  - `desired_state`
  - `final_state`
  - `active_version`
  - `previous_version`
  - `changed`
  - `state_transition`
  - `error`
  - `compose_project_name`
- Supervisor loop now executes:
  - `result = reconcile_one(addon_dir)`
  - `run_post_reconcile_hooks(addon_dir, result)` when result exists

Implemented initial post-reconcile hooks:
- Artifact retention cleanup hook:
  - runs only for successful `final_state=running` results
  - keeps active + previous + newest versions per retention policy
- Lifecycle event emission hook:
  - emits/logs `addon_started`, `addon_updated`, `addon_failed` payloads based on result transition/outcome

Boundary:
- `runtime.json` write semantics remain unchanged (atomic write per reconcile attempt where `desired.json` exists).

## 2) Addon Directory Discovery

Implemented:
- Each direct subdirectory under `SYNTHIA_ADDONS_DIR/services/` is treated as a candidate addon.
- If a candidate directory has no `desired.json`, it is skipped.

Not developed:
- Explicit addon directory registration/allowlist.
- Recursive nested directory discovery.

## 3) Version Resolution Logic

### Important questions

- Does Core translate `latest` into a real version before writing `desired.json`?
  - **Answer (code):** In normal store install flow, Core writes `pinned_version=body.pinned_version or manifest.version` (`router.py`), so usually a concrete version is written.
  - **Edge case present in code:** if `pinned_version` is missing/`null`, supervisor falls back to string `latest` (`version = desired.pinned_version or "latest"`).

- Does the supervisor ever resolve catalog versions?
  - **Answer (code):** **No.** Supervisor does not query catalog state.

- What happens if `latest` changes?
  - **Answer (code):** **Not developed** as catalog-aware behavior. `latest` is treated as a literal local version directory name (`versions/latest`).

## 4) Docker Compose Project Naming

Implemented:
- Supervisor passes `desired.runtime.project_name` to Docker Compose `-p` in both `up` and `down` calls.

Operational implication from Docker Compose behavior:
- `project_name` defines compose stack identity (resource naming scope).
- If project name changes between desired states/versions, cleanup continuity can change because `down` targets the project name in the current desired runtime payload.

Not developed:
- Project-name migration safeguards/warnings.

## 5) Artifact Extraction Behavior

Implemented:
- Artifact extraction target is `versions/<version>/extracted/`.
- Extraction is one-time per version directory in current logic:
  - if `extracted/` already exists, extraction is skipped.
  - otherwise `tar -xzf addon.tgz -C extracted/` is executed.
- After extract (and on extract-skip), supervisor normalizes mtimes in `extracted/` so Docker build context diffing picks up current file content reliably.

Not developed:
- Automatic re-extract when `addon.tgz` changes in-place while `extracted/` already exists.

## 6) Environment Variable Handling

Implemented:
- `runtime.env` is rewritten each running reconcile from `desired.config.env` values.
- Keys are sorted before write.
- If `SYNTHIA_SERVICE_TOKEN` exists in supervisor process environment, it is injected unless already present in desired env.

Important handling detail:
- Supervisor writes raw `KEY=VALUE` lines; it does not perform shell evaluation/expansion itself.
- Any runtime expansion behavior is left to Docker Compose/container runtime semantics.

## 7) Compose File Ownership

Implemented:
- Supervisor generates `versions/<version>/docker-compose.yml` only if missing.
- If compose file already exists and compose-impacting desired inputs are unchanged, supervisor leaves it unchanged.
- If compose file already exists and compose-impacting desired inputs change for the same active version, supervisor regenerates compose by replacing the file before template write.

Implication:
- Custom compose file content in that path is preserved and used on future reconciles.

Not developed:
- Compose template versioning/validation against expected schema.

## 7.1) Desired Update Notification and Rebuild Trigger

Implemented:
- Supervisor has no direct notify endpoint/event bus for desired updates.
- Supervisor detects desired changes by reading `desired.json` during polling reconcile.
- Core Store writes desired updates via atomic replace; supervisor consumes the latest file snapshot on the next poll.

Important rebuild boundary:
- `runtime.env` is rewritten each running reconcile, so desired env changes are applied.
- Core writes `desired_revision`; supervisor persists the last applied marker in `runtime.json`.
- When `desired_revision` is unchanged and runtime is already `running` on the same version, supervisor no-ops (skips extract/compose/up).
- Compose-affecting desired fields are digested by supervisor; if digest changes on same version, supervisor regenerates compose before `compose up`.
- `force_rebuild=true` in desired payload forces one rebuild/recreate cycle for that `desired_revision` (then no-op resumes for unchanged revision).
- On desired pinned-version transition from previous active version, supervisor runs compose with rebuild/recreate semantics to avoid stale local image reuse.
- On first activation (no prior running runtime/active version), supervisor also runs compose with rebuild/recreate semantics to avoid stale local image reuse on reinstall.
- Rebuild path executes `docker compose build --no-cache` before `docker compose up --force-recreate`.

## 8) Container Build Model

Implemented:
- Generated compose template uses `build: <versions/<version>/extracted>`.

Implication:
- Artifact must expand into a valid Docker build context.
- Build context must contain what Docker needs (for example Dockerfile and referenced files).

Not developed:
- Preflight validation of build context before invoking `docker compose up`.

## 9) Health Check Model (Missing)

### Important questions

- Does supervisor check container health?
  - **Answer (code):** **No active health checks implemented.**

- Does it call `/health` endpoints?
  - **Answer (code):** **No.**

- Does it only rely on Docker?
  - **Answer (code):** Runtime actions are Docker Compose `up/down`.
  - Runtime model includes no active supervisor-managed HTTP probing.

## 10) Upgrade Semantics (Partially Defined)

### Important questions

- Does supervisor automatically upgrade when desired version changes?
  - **Answer (code):** Yes, when the desired target version differs (typically through `desired.pinned_version`) and reconcile prerequisites succeed.
  - **Clarification:** Supervisor does not resolve versions from catalog metadata; it uses the desired payload as written.

- Is old container stopped first?
  - **Answer (code):** **No explicit pre-stop path** for upgrade. Running path performs `compose up -d` for target compose/project and switches `current` symlink after success.
  - **Clarification:** Supervisor does **not** implement staged/canary upgrade orchestration.

- Is rollback automatic or manual?
  - **Answer (code):** **Automatic rollback execution is not developed.**
  - Implemented today: rollback metadata only (`previous_version`, `rollback_available`, `last_error`).
  - Rollback metadata is informational; supervisor does not automatically revert to a previous version on failure.

## 11) Failure Retry Model

Implemented:
- Reconcile errors set `runtime.json` to `state="error"`.
- Addon is retried automatically on next polling cycle because it remains in directory iteration.
- There is no permanent quarantine list in supervisor code.

Not developed:
- Retry backoff per-addon.
- Circuit-breaker/quarantine state.

## 12) `runtime.json` Lifecycle

Implemented:
- Runtime object starts in-memory as `installing` at reconcile start.
- `runtime.json` is atomically rewritten at the end of reconcile attempt for directories with `desired.json`.
- Stable persisted states confirmed by code paths:
  - `running`
  - `stopped`
  - `error`
- `installing` is initialization state used during reconcile execution, then replaced by terminal state write.
- Runtime state includes last-applied desired metadata (`last_applied_desired_revision`, `last_applied_compose_digest`) for deterministic change detection.

Not developed:
- Historical event log in `runtime.json`.

## 12.1) Core Runtime Aggregation Interface

Implemented in Core (outside supervisor process):
- `GET /api/system/addons/runtime`
- `GET /api/system/addons/runtime/{addon_id}`
- Runtime payloads are merged from:
  - supervisor `runtime.json`
  - Core-written `desired.json`
  - Docker container inspect metadata (when Docker is reachable)

Boundary clarification:
- This runtime aggregation is read-only and does not mutate supervisor state.
- Store status/diagnostics runtime fields are sourced through the same aggregation service.

## 13) Concurrency / Locking (Important)

### Important questions

- What if Core writes `desired.json` mid-reconcile?
  - **Answer (code):** No cross-process lock/transaction contract. Core uses atomic replace for desired writes; supervisor reads a file snapshot.

- What if multiple supervisors run?
  - **Answer (code):** **Not developed** multi-supervisor coordination (no leader election/lock manager).

- Is `runtime.json` locked?
  - **Answer (code):** No explicit lock. Writes are atomic replace.

## 14) Artifact Integrity Model

Current development policy:
- Artifact checksum and signature enforcement are intentionally disabled during the active development phase.
- Reconcile currently requires artifact file existence only.
- Reconcile logs verification skipped and does not call signature/checksum verification.

Status:
- Runtime verification enforcement in reconcile: **Not developed (disabled in current path).**
- Verification utility code exists in `crypto.py` but is intentionally not invoked by current reconcile flow unless project policy changes.

## 15) Out of Scope for Current Supervisor (Not Developed)

The following capabilities are intentionally not implemented in the current supervisor:
- Catalog checksum enforcement in reconcile path
- Publisher signature verification in reconcile path
- Automatic rollback execution
- HTTP health probing of addon containers
- Prometheus/OpenMetrics endpoint
- Network policy enforcement
- Multi-supervisor coordination
- Distributed locking

## 16) Resource Limits

Implemented in generated compose when specified in desired runtime:
- `cpus` (from `desired.runtime.cpu`)
- `mem_limit` (from `desired.runtime.memory`)

Behavior:
- Resource limits are optional; when fields are absent, compose omits these keys.
- Existing addon versions continue to run without resource overrides.

Not developed:
- pids limits
- IO limits
- full policy validation/normalization for memory unit formats

## 17) Network Isolation Model (Partial)

Implemented:
- Explicit network name from desired runtime (`runtime.network`, default `synthia_net`).
- Generated template does not set `network_mode: host`.
- Ports are only published when specified.
- Bind defaults to `127.0.0.1`; optional `0.0.0.0` when `bind_localhost=false`.

Not developed:
- Network policy engine (ACL/egress controls).
- Per-addon hard isolation policy beyond compose network selection.

### Important questions

- Does container auto restart?
  - **Answer (code):** Yes, generated compose sets `restart: unless-stopped`.

- Only supervisor restart?
  - **Answer (code):** Supervisor process is also restart-managed by systemd (`Restart=always`).

## 18) Disk Growth / Cleanup

Implemented behavior:
- Supervisor performs post-success version retention cleanup after running reconcile.
- Cleanup keeps:
  - active version
  - previous version (when present)
  - additional newest versions until keep-count target is met
- Default keep-count is `3`; configurable via `SYNTHIA_SUPERVISOR_KEEP_VERSIONS` (minimum enforced keep-count: `2`).
- Cleanup runs only after successful reconcile; failure paths do not prune versions.
- Pruning removes old version directories (including unused extracted/build-context artifacts inside pruned versions).

Not developed:
- Docker image pruning/cleanup in supervisor code.

## 19) Security Boundary Model

Implemented controls in generated compose:
- `privileged: false`
- `security_opt: no-new-privileges:true`

Explicit boundary statement:
- Supervisor is orchestration glue, **not a sandbox**.
- Standalone addon containers are trusted to the level allowed by host Docker daemon policy and supplied compose/build content.

Not developed:
- Independent policy sandbox beyond compose defaults.

## 20) Runtime Assumptions

The current supervisor operates under these assumptions:
- Docker daemon is available and trusted by the operator environment.
- Artifacts staged by Core are trusted development inputs.
- Core writes valid `desired.json` payloads.
- Standalone addons are trusted workloads and are not sandboxed by supervisor.

## 21) Supervisor Failure Recovery

Implemented:
- Reconcile exceptions are caught per addon.
- Error state is persisted to `runtime.json` and loop continues.
- systemd can restart supervisor process if it exits.

Not developed:
- Replayable reconcile journal.
- Fine-grained backoff/circuit-breaker controls.

## 22) Supervisor Upgrade Safety

Implemented behavior from process model:
- Supervisor restart/upgrade does not explicitly stop running addon containers in code.
- Running containers remain managed by Docker (`restart: unless-stopped`) unless external actions stop them.
- After restart, supervisor resumes polling and reconciling current desired state.

Not developed:
- Explicit supervisor upgrade transaction protocol.

## 23) Configuration Schema (Desired State Example)

Core writes desired payload with strict validation in `standalone_desired.py`.

Example shape:

```json
{
  "ssap_version": "1.0",
  "addon_id": "mqtt",
  "mode": "standalone_service",
  "desired_state": "running",
  "desired_revision": "1741464210123456789",
  "force_rebuild": false,
  "channel": "stable",
  "pinned_version": "0.1.2",
  "install_source": {
    "type": "catalog",
    "catalog_id": "official",
    "release": {
      "artifact_url": "https://example/addon.tgz",
      "sha256": "",
      "publisher_key_id": "",
      "signature": {
        "type": "none",
        "value": ""
      }
    }
  },
  "runtime": {
    "orchestrator": "docker_compose",
    "project_name": "synthia-addon-mqtt",
    "network": "synthia_net",
    "cpu": 1.0,
    "memory": "512m",
    "ports": [
      {"host": 9002, "container": 9002, "proto": "tcp"}
    ],
    "bind_localhost": true
  },
  "config": {
    "env": {
      "CORE_URL": "http://127.0.0.1:8000",
      "SYNTHIA_ADDON_ID": "mqtt",
      "SYNTHIA_SERVICE_TOKEN": "${SYNTHIA_SERVICE_TOKEN}"
    }
  }
}
```

Note:
- Supervisor runtime model consumes fields required for reconciliation; some Core payload fields (for example `mode`, `channel`) are not used in current supervisor logic.

## 24) Addon Contract (Container Expectations)

Expected by current code path:
- `versions/<version>/addon.tgz` exists.
- Artifact can be extracted by `tar -xzf`.
- Extracted directory is a valid Docker build context.
- Runtime accepts env-file based configuration.

Not developed in supervisor:
- Explicit runtime endpoint contract enforcement.
- Built-in addon liveness/readiness contract checks.

## 25) Observability (Metrics)

Implemented:
- Structured logging via `synthia.supervisor` logger.
- `runtime.json` status with key operational fields (`state`, `active_version`, `last_error`, rollback metadata).
- Core system stats service reports supervisor unit status (`synthia-supervisor.service`).

Not developed:
- Native Prometheus/OpenMetrics endpoint.
- Reconcile latency/counter metrics endpoint.

## 26) Supervisor API (Missing)

Status:
- No direct HTTP API exposed by supervisor.
- Control plane is file-based (`desired.json` input, `runtime.json` output) plus systemd process control.

## 27) Architecture Diagram

```text
+--------------------+                              +---------------------------+
| Core Store Install |                              | User systemd              |
| (router.py)        |                              | synthia-supervisor.service|
+---------+----------+                              +-------------+-------------+
          |                                                         |
          | stage addon.tgz + write desired.json                    | starts
          v                                                         v
+--------------------------------------------------------------------------+
| SYNTHIA_ADDONS_DIR/services/<addon_id>/                                  |
|  - desired.json (Core writes)                                            |
|  - versions/<version>/addon.tgz (Core stages)                            |
|  - runtime.json (Supervisor writes)                                      |
|  - current -> versions/<version>                                         |
+-------------------------------+------------------------------------------+
                                |
                                | poll + reconcile (main.py)
                                v
                      +----------------------------+
                      | Supervisor reconcile_one() |
                      | - load desired             |
                      | - ensure extract/compose   |
                      | - docker compose up/down   |
                      | - update runtime.json      |
                      +-------------+--------------+
                                    |
                                    v
                          +----------------------+
                          | Docker Engine/Compose|
                          +----------------------+
```

## 28) Important Questions Checklist (Preserved)

1. Version Resolution Logic
- Does Core translate `latest` into a real version before writing `desired.json`?
- Does supervisor ever resolve catalog versions?
- What happens if `latest` changes?

2. Health Check Model
- Does supervisor check container health?
- Does it call `/health` endpoints?
- Does it only rely on Docker?

3. Upgrade Semantics
- Does supervisor automatically upgrade when desired version changes?
- Is old container stopped first?
- Is rollback automatic or manual?

4. Concurrency / Locking
- What if Core writes `desired.json` mid-reconcile?
- What if multiple supervisors run?
- Is `runtime.json` locked?

5. Artifact Integrity Model
6. Resource Limits
7. Network Isolation Model
- Does container auto restart?
- Only supervisor restart?

8. Disk Growth / Cleanup
9. Supervisor Failure Recovery
10. Configuration Schema
11. Addon Contract
12. Observability
13. Supervisor API
14. Architecture Diagram

## 29) File Ownership and Expectations

### `manifest.json`

Supervisor ownership:
- Supervisor does not parse or validate addon `manifest.json` fields directly.

Supervisor expectation from addon artifact:
- Docker build context must be valid for the addon Dockerfile.
- If Dockerfile copies `manifest.json` (or other paths), those files must exist in extracted artifact.

Store responsibility boundary:
- Store/catalog pipeline validates `ReleaseManifest` schema before writing standalone desired intent.

### `desired.json`

Ownership:
- Core Store writes `desired.json`.
- Supervisor reads `desired.json` as reconcile input.

Supervisor-required fields (from current `DesiredState` model usage):
- top-level: `ssap_version`, `addon_id`, `desired_state`, `desired_revision`, `force_rebuild`, `enabled_docker_groups`, `pinned_version` (optional), `install_source`, `runtime`, `config`
- runtime fields consumed for reconcile behavior: `project_name`, `network`, `ports`, `bind_localhost`, `cpu`, `memory`
- install source release field used by model: `artifact_url` (artifact file path is still sourced from staged local `addon.tgz`)

Field usage boundary:
- Supervisor ignores some Core-authored fields present in desired payload (for example `mode`, `channel`, `install_source.catalog_id`).

### `runtime.json`

Ownership:
- Supervisor writes `runtime.json` (atomic replace).
- Core reads `runtime.json` for status/diagnostics.
- Machine-readable reference schema: `docs/runtime.schema.json`.

Supervisor-written state fields:
- `ssap_version`
- `addon_id`
- `active_version`
- `state` (`running|stopped|error`)
- `error`
- `previous_version`
- `rollback_available`
- `last_error`
- `last_applied_desired_revision`
- `last_applied_compose_digest`
- `last_force_rebuild_revision`
- `requested_docker_groups`
- `active_docker_groups`
- `failed_docker_groups`
- `compose_files_in_use`

Optional docker-group reconcile model:
- Base compose file remains `versions/{version}/docker-compose.yml`.
- Optional group override files are discovered under extracted artifact path with naming convention:
  - `docker-compose.group-<group>.yml`
- Supervisor compose up/down uses base + discovered group override files with `--remove-orphans`.
- Runtime reporting distinguishes:
  - requested groups (`enabled_docker_groups` intent)
  - active groups (override file found and included)
  - failed groups (requested but override file missing)

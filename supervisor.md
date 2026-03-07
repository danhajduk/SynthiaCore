# Synthia Supervisor: Core-System Deep Dive

This document describes how the standalone addon supervisor currently works in Synthia, based on the implementation and tests in this repository.

Primary source code:
- `backend/synthia_supervisor/main.py`
- `backend/synthia_supervisor/docker_compose.py`
- `backend/synthia_supervisor/models.py`
- `backend/synthia_supervisor/crypto.py` (verification utility; currently not called by reconcile loop)

Core integration paths:
- `backend/app/store/router.py`
- `backend/app/store/standalone_paths.py`
- `backend/app/store/standalone_desired.py`
- `backend/app/system/stats/service.py`
- `systemd/user/synthia-supervisor.service.in`

## 1. Supervisor Purpose and Responsibility Boundary

Supervisor role:
- Watch standalone service addon directories under `SYNTHIA_ADDONS_DIR/services`.
- Read desired state from `desired.json`.
- Materialize runtime artifacts (`extracted`, compose file, env file) per target version.
- Start/stop service containers with Docker Compose.
- Write actual runtime state to `runtime.json`.

Boundary with Core:
- Core handles catalog resolution, artifact download, and artifact staging (`addon.tgz`).
- Core writes desired intent (`desired.json`) and reads runtime status (`runtime.json`) for APIs/UI.
- Supervisor is the runtime reconciler; Core does not directly launch standalone service containers in this path.

## 2. Process Model and Startup

Entrypoint:
- `python -m synthia_supervisor.main`

Long-running behavior:
- Infinite loop in `main()`.
- Iterates all directories under `services/`.
- Calls `reconcile_one(addon_dir)` for each addon directory.
- Sleeps for configured interval before next pass.

Default runtime configuration (code):
- `DEFAULT_INTERVAL_S = 5`
- default log level = `INFO`

Relevant environment variables:
- `SYNTHIA_ADDONS_DIR`
  - Supervisor default: `../SynthiaAddons` (resolved absolute).
- `SYNTHIA_SUPERVISOR_INTERVAL_S`
  - Poll interval in seconds.
- `SYNTHIA_SUPERVISOR_LOG_LEVEL`
  - Standard Python logging level string.
- `SYNTHIA_SERVICE_TOKEN`
  - Injected into generated `runtime.env` unless already set in desired config env.

User systemd unit template:
- `systemd/user/synthia-supervisor.service.in`
- Includes:
  - `Environment=SYNTHIA_ADDONS_DIR=%h/Projects/SynthiaAddons`
  - `Environment=SYNTHIA_CATALOG_PUBLISHERS=@INSTALL_DIR@/runtime/store/cache/official/publishers.json`
  - `Environment=SYNTHIA_SUPERVISOR_INTERVAL_S=5`
  - `ExecStart=@INSTALL_DIR@/backend/.venv/bin/python -m synthia_supervisor.main`
  - `Restart=always`

## 3. Filesystem Layout and Ownership

Supervisor expects this structure (per addon):

```text
<SYNTHIA_ADDONS_DIR>/services/<addon_id>/
  desired.json                  # Core-owned desired intent
  runtime.json                  # Supervisor-owned actual state
  current -> versions/<version> # Active version symlink
  versions/
    <version>/
      addon.tgz                 # Core-staged artifact
      extracted/                # Supervisor extraction target
      docker-compose.yml        # Supervisor-generated
      runtime.env               # Supervisor-generated
```

Ownership model:
- Core writes: `desired.json`, artifact staging under `versions/<version>/addon.tgz`.
- Supervisor writes: `runtime.json`, `runtime.env`, compose file, extraction output, `current` symlink switch.

## 4. Data Contracts Used in Runtime

### 4.1 Desired state consumed by supervisor

`backend/synthia_supervisor/models.py::DesiredState` expects:
- `ssap_version`
- `addon_id`
- `desired_state`
- `pinned_version` (optional)
- `install_source` (with `release` info)
- `runtime` (`project_name`, `network`, `ports`, `bind_localhost`)
- `config` (`env` map)

Core writes desired payload via `build_desired_state` in `backend/app/store/standalone_desired.py`.

Important schema note:
- Core desired payload includes `mode` and `channel`.
- Supervisor model does not use those fields for reconciliation logic.

### 4.2 Runtime state produced by supervisor

`backend/synthia_supervisor/models.py::RuntimeState` fields:
- `ssap_version`
- `addon_id`
- `active_version`
- `state`
- `error`
- `previous_version`
- `rollback_available`
- `last_error`

Initialization:
- New runtime object starts as `state="installing"` before reconcile actions complete.

## 5. Reconciliation Logic in Detail

`reconcile_one(addon_dir)` flow:

1. Check for `desired.json`.
   - If missing: skip directory.
2. Parse desired payload into `DesiredState`.
3. Resolve previously active version from `current` symlink.
4. Branch by `desired_state`.

### 5.1 `desired_state == "stopped"`

Behavior:
- Compose file path is `<addon_dir>/current/docker-compose.yml`.
- If compose file exists, run `docker compose down` with runtime `project_name`.
- Write `runtime.json` with `state="stopped"`.

### 5.2 `desired_state != "stopped"` (running path)

Target version selection:
- `version = desired.pinned_version or "latest"`

Per-version paths:
- `version_dir = versions/<version>`
- `artifact_path = version_dir/addon.tgz`
- `extracted_dir = version_dir/extracted`
- `compose_file = version_dir/docker-compose.yml`
- `env_file = version_dir/runtime.env`

Running path steps:
1. Ensure version directory exists.
2. Require artifact presence.
   - Missing artifact raises `RuntimeError("Artifact missing")`.
3. Signature verification:
   - Current loop logs `verify_skipped ... signature_checks_disabled`.
   - No verification call occurs in current reconcile path.
4. Extract artifact if needed (`tar -xzf` into `extracted/`).
5. Generate/update runtime env file and compose file.
6. Run `docker compose up -d`.
7. Atomically switch `current` symlink to `version_dir`.
8. Set runtime state to running and write success metadata.

On success runtime metadata:
- `state="running"`
- `active_version=<version>`
- `previous_version=<previous current version>`
- `rollback_available=true` only if previous version exists and differs.
- `last_error=None`

## 6. Compose and Environment File Generation

Implemented in `backend/synthia_supervisor/docker_compose.py`.

### 6.1 `runtime.env` generation

Each reconcile writes `runtime.env` from desired config env map, sorted keys.

Token injection behavior:
- If process env has `SYNTHIA_SERVICE_TOKEN`, it is added unless already present in desired env.

### 6.2 Compose generation rules

Compose file is generated only if missing.
- If `docker-compose.yml` already exists for that version, generation is skipped.

Default guardrails embedded in generated compose:
- `privileged: false`
- `security_opt: [no-new-privileges:true]`
- dedicated named network from desired runtime network (default in model is `synthia_net`)

Port publishing behavior:
- Desired runtime `ports` list accepts dict items with `host`, `container`, optional `proto`.
- Default bind host:
  - `127.0.0.1` when `bind_localhost` true (default)
  - `0.0.0.0` when `bind_localhost` false

Generated port mapping format:
- `"host_bind:host_port:container_port/proto"`

## 7. Docker Command Execution and Error Propagation

Compose command runner:
- `_run_compose_command(args, action)` executes subprocess with captured stdout/stderr.
- On non-zero exit:
  - Picks summary from stderr, else stdout, else exit code token.
  - Logs `<action>_failed rc=<code> summary=<last line>`.
  - Raises `RuntimeError(f"{action}_failed: {tail_line}")`.

Used by:
- `compose_up(...)` -> `docker compose ... up -d`
- `compose_down(...)` -> `docker compose ... down`

## 8. Atomic Activation and Rollback Metadata

Activation mechanism:
- `activate_current_symlink(addon_dir, version_dir)` creates `.current.next` symlink, then atomically renames to `current`.
- This prevents partial state where `current` points nowhere during switch.

Failure safety behavior:
- `current` is switched only after successful `compose_up`.
- If `compose_up` fails, existing `current` remains unchanged.

Rollback signals written to `runtime.json`:
- `previous_version`
- `rollback_available`
- `last_error`

## 9. Failure Handling Semantics

All reconcile errors are caught in `reconcile_one` and converted to runtime error state:
- `state="error"`
- `error=<exception string>`
- `last_error=<same message>`
- `previous_version=<resolved from current link before attempt>`
- `rollback_available=<bool(previous_version)>`

`runtime.json` is still written after failure, so Core can surface diagnostics.

## 10. Logging Model

Logger name:
- `synthia.supervisor`

Current loop logs include:
- startup (`supervisor_start`)
- desired load and state metadata
- stop path decisions
- artifact missing errors
- extraction and compose file generation from helper module
- reconcile completion (`state=running` or `state=stopped`)
- full exception trace on reconcile failure (`reconcile_error`)

Log level control:
- `SYNTHIA_SUPERVISOR_LOG_LEVEL` env var

## 11. Core-System Integration Points

## 11.1 Install flow writes desired state for supervisor

In `backend/app/store/router.py` standalone install branch:
- Stages artifact to `services/<addon_id>/versions/<version>/addon.tgz`.
- Builds desired payload via `build_desired_state(...)`.
- Atomically writes `desired.json`.
- Returns install response metadata including:
  - `desired_path`, `runtime_path`, `staged_artifact_path`
  - `runtime_state`
  - `supervisor_expected`
  - `supervisor_hint` when runtime not yet known

Guardrails enforced by Core before writing desired intent:
- Reject host network overrides (`host` / `host_network`).
- Reject privileged runtime override.
- Default `bind_localhost=true` unless overridden.

## 11.2 Runtime status read path

Core helper `_read_standalone_runtime(addon_id)` in `router.py`:
- Reads `runtime.json` if present.
- Surfaces:
  - `runtime_state`
  - `standalone_runtime` summary (`state`, `active_version`, `last_action`, `health`, `error`, `last_error`)
  - `runtime_path`

Diagnostics endpoint also derives `last_error_summary` from `last_error` or `error`.

Important compatibility note:
- Core reader still includes legacy keys `last_action` and `health` when present.
- Current supervisor runtime model does not actively populate those fields.

## 11.3 System metrics service visibility

`backend/app/system/stats/service.py` includes supervisor in `_SERVICE_UNITS` as:
- `synthia-supervisor.service`

This status is exposed in system metrics APIs/UI as part of service health visibility.

## 12. Security Posture in Current Implementation

Positive controls:
- Compose defaults include `privileged: false` and `no-new-privileges`.
- Network is explicit and not host-mode by default.
- Port publishing defaults to localhost unless explicitly widened.
- Runtime env injection supports service token without hardcoding token value in repo.

Current caveat:
- Reconcile loop logs verification as skipped and does not enforce signature/checksum verification today.
- `crypto.py` contains verification utilities and publisher registry loading, but reconcile path currently bypasses them.

## 13. Test Coverage and What It Proves

Supervisor reconcile tests (`backend/tests/test_synthia_supervisor_main.py`) validate:
- Operation order: extract -> compose files -> compose up.
- Error short-circuiting when extraction fails.
- No `current` symlink switch when compose up fails.
- Upgrade success updates `current`, `previous_version`, and rollback metadata.

Compose tests (`backend/tests/test_synthia_supervisor_compose.py`) validate:
- Compose guardrails (`privileged: false`, `no-new-privileges`, dedicated network).
- Port bind behavior for localhost vs host publish.
- `compose_up` failure surfaces concise stderr summary in raised error.

Crypto tests (`backend/tests/test_synthia_supervisor_crypto.py`) validate utility behavior:
- Default publisher registry path resolution.
- Missing registry path diagnostic quality.
- Legacy RSA signature compatibility path in `verify_release_option_a`.

## 14. Operational Behavior Summary

From operator perspective:
- Install standalone addon via Core store endpoint.
- Core stages artifact and writes desired state.
- Supervisor loop detects desired intent and reconciles.
- Runtime status appears in `runtime.json`.
- Core APIs/UI reflect runtime status and any error summary.

Practical troubleshooting sequence:
1. Confirm supervisor unit is running (`synthia-supervisor.service`).
2. Check addon `desired.json` and `runtime.json` under `SYNTHIA_ADDONS_DIR/services/<addon_id>/`.
3. Inspect `runtime.json:last_error` for reconcile failure cause.
4. Inspect supervisor logs for compose/extract failure details.
5. Confirm staged artifact exists at `versions/<version>/addon.tgz`.

## 15. Key Implementation Realities (As of Current Code)

- Reconciliation is polling-based, not event-driven.
- `docker-compose.yml` is version-scoped and only auto-generated if missing.
- `runtime.env` is regenerated every reconcile cycle for running path.
- Activation is atomic at symlink switch time.
- Failures preserve previous active deployment pointer and expose rollback hints.
- Verification logic exists in codebase but is not currently enforced in reconcile loop.

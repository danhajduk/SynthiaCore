# Synthia Supervisor Runtime Specification (Code-Verified)

This document only describes behavior that is present in code today. Any missing capability is explicitly labeled **Not developed**.

Code sources used:
- `backend/synthia_supervisor/main.py`
- `backend/synthia_supervisor/docker_compose.py`
- `backend/synthia_supervisor/models.py`
- `backend/synthia_supervisor/crypto.py`
- `backend/app/store/router.py`
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
- If compose file already exists, supervisor leaves it unchanged.

Implication:
- Custom compose file content in that path is preserved and used on future reconciles.

Not developed:
- Compose template versioning/validation against expected schema.

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
  - **Answer (code):** Yes, if target version artifact exists and reconcile succeeds.

- Is old container stopped first?
  - **Answer (code):** **No explicit pre-stop path** for upgrade. Running path performs `compose up -d` for target compose/project and switches `current` symlink after success.

- Is rollback automatic or manual?
  - **Answer (code):** **Automatic rollback execution is not developed.**
  - Implemented today: rollback metadata only (`previous_version`, `rollback_available`, `last_error`).

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

Not developed:
- Historical event log in `runtime.json`.

## 13) Concurrency / Locking (Important)

### Important questions

- What if Core writes `desired.json` mid-reconcile?
  - **Answer (code):** No cross-process lock/transaction contract. Core uses atomic replace for desired writes; supervisor reads a file snapshot.

- What if multiple supervisors run?
  - **Answer (code):** **Not developed** multi-supervisor coordination (no leader election/lock manager).

- Is `runtime.json` locked?
  - **Answer (code):** No explicit lock. Writes are atomic replace.

## 14) Artifact Integrity Model

Current reconcile path behavior:
- Requires artifact file existence.
- Logs verification skipped.
- Does not call signature/checksum verification in reconcile loop.

Status:
- Runtime verification enforcement in reconcile: **Not developed (disabled in current path).**
- Verification utility code exists in `crypto.py` but is not used by current reconcile flow.

## 15) Resource Limits (Missing)

Generated compose does not set:
- CPU limits/reservations
- memory limits/reservations
- pids limits
- IO limits

Status:
- Resource governance policy in supervisor compose generation: **Not developed**.

## 16) Network Isolation Model (Partial)

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

## 17) Disk Growth / Cleanup (Important)

Implemented behavior:
- Version folders, extracted trees, runtime env files, and compose files persist.
- No automatic cleanup/pruning in supervisor code.

Status:
- Retention and garbage collection policy: **Not developed**.

## 18) Security Boundary Model

Implemented controls in generated compose:
- `privileged: false`
- `security_opt: no-new-privileges:true`

Explicit boundary statement:
- Supervisor is orchestration glue, **not a sandbox**.
- Standalone addon containers are trusted to the level allowed by host Docker daemon policy and supplied compose/build content.

Not developed:
- Independent policy sandbox beyond compose defaults.

## 19) Supervisor Failure Recovery

Implemented:
- Reconcile exceptions are caught per addon.
- Error state is persisted to `runtime.json` and loop continues.
- systemd can restart supervisor process if it exits.

Not developed:
- Replayable reconcile journal.
- Fine-grained backoff/circuit-breaker controls.

## 20) Supervisor Upgrade Safety

Implemented behavior from process model:
- Supervisor restart/upgrade does not explicitly stop running addon containers in code.
- Running containers remain managed by Docker (`restart: unless-stopped`) unless external actions stop them.
- After restart, supervisor resumes polling and reconciling current desired state.

Not developed:
- Explicit supervisor upgrade transaction protocol.

## 21) Configuration Schema (Desired State Example)

Core writes desired payload with strict validation in `standalone_desired.py`.

Example shape:

```json
{
  "ssap_version": "1.0",
  "addon_id": "mqtt",
  "mode": "standalone_service",
  "desired_state": "running",
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

## 22) Addon Contract (Container Expectations)

Expected by current code path:
- `versions/<version>/addon.tgz` exists.
- Artifact can be extracted by `tar -xzf`.
- Extracted directory is a valid Docker build context.
- Runtime accepts env-file based configuration.

Not developed in supervisor:
- Explicit runtime endpoint contract enforcement.
- Built-in addon liveness/readiness contract checks.

## 23) Observability (Metrics)

Implemented:
- Structured logging via `synthia.supervisor` logger.
- `runtime.json` status with key operational fields (`state`, `active_version`, `last_error`, rollback metadata).
- Core system stats service reports supervisor unit status (`synthia-supervisor.service`).

Not developed:
- Native Prometheus/OpenMetrics endpoint.
- Reconcile latency/counter metrics endpoint.

## 24) Supervisor API (Missing)

Status:
- No direct HTTP API exposed by supervisor.
- Control plane is file-based (`desired.json` input, `runtime.json` output) plus systemd process control.

## 25) Architecture Diagram

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

## 26) Important Questions Checklist (Preserved)

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

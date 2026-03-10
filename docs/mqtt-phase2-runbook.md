# MQTT Embedded Phase 2 Runbook

Last Updated: 2026-03-10 06:56 US/Pacific

## Scope

This runbook covers implemented Phase 2 operations for Core-owned embedded MQTT authority:
- effective access inspection
- principal lifecycle actions
- generic user lifecycle operations
- noisy-client state/actions
- degraded-state and recovery checks in API/UI

## State and Runtime Files

Authority state:
- `var/mqtt_integration_state.json`

Authority audit:
- `var/mqtt_authority_audit.db`

Observability events:
- `var/mqtt_observability.db`

Live runtime artifacts:
- `var/mqtt_runtime/live/*`

Local broker runtime container:
- name: `synthia-mqtt-broker` (default)
- image: `eclipse-mosquitto:2` (default)
- runtime provider selection: `SYNTHIA_MQTT_RUNTIME_PROVIDER` (`docker` default, `memory` for deterministic test mode)

## Health and Degraded-State Checks

Primary checks:
- `GET /api/system/mqtt/setup-summary`
- `GET /api/system/mqtt/health`
- `GET /api/system/mqtt/status`

Degraded indicators (implemented):
- `effective_status.status = degraded`
- `effective_status.reasons[]` includes one or more of:
  - `authority_not_ready`
  - `setup_not_ready`
  - `mqtt_runtime_not_connected`
- `health.last_error` shows latest runtime error when present
- `reconciliation.last_reconcile_status|last_reconcile_error` shows last apply/reload result
- `bootstrap_publish.published|last_error` shows bootstrap publish readiness/failure

Core UI surface:
- Settings > Connectivity shows authority status, runtime error, last apply/reload result, bootstrap publish state
- Settings > MQTT Infrastructure Admin card shows runtime health and audit/observability logs

## Effective Access Inspection

Inspect one principal:
- `GET /api/system/mqtt/debug/effective-access/{principal_id}`

Generic-user scoped view:
- `GET /api/system/mqtt/generic-users/{principal_id}/effective-access`

Implemented behavior:
- revoked/expired principals return no effective access
- `noisy_state=blocked` returns empty publish/subscribe scopes with deny-all behavior
- generic users are filtered to non-reserved topics and include reserved deny families
- anonymous principal is bootstrap-only subscribe

## Principal Lifecycle Actions

List principals:
- `GET /api/system/mqtt/principals`

Apply lifecycle action:
- `POST /api/system/mqtt/principals/{principal_id}/actions/{action}`

Implemented actions:
- `activate`
- `revoke`
- `expire`
- `probation`
- `promote`

Each action writes authority state and triggers runtime reconcile.

### Addon Principal Pending Root Cause (Task 342)

Observed root cause:
- `addon:mqtt` principal status tracks grant status from authority state.
- when setup was previously degraded, `provision_grant` persisted grant `status=error` (`mqtt_setup_not_ready:*`), so principal stayed `pending`.
- later runtime recovery did not auto-promote existing `approved/error` grants to `active` without explicit reprovision.

Implemented fix:
- startup/runtime authority reconcile now promotes eligible addon grants (`approved|error|provisioned`) to `active` after successful runtime apply.
- the same promote step updates matching addon principals to `status=active`.
- Core startup explicitly runs `mqtt_registration_approval.reconcile("mqtt")` for enabled addon `mqtt` to ensure registration bootstrap on startup.

## Generic User Lifecycle

Create user (operator contract):
- `POST /api/system/mqtt/users`
- request fields:
  - `username`
  - `password` (`generated` for auto-generated credential)
  - `topic_prefix` (must resolve to `external/<username>`)

Create or update generic user:
- `POST /api/system/mqtt/generic-users`

Update grants:
- `PATCH /api/system/mqtt/generic-users/{principal_id}/grants`

Revoke generic user:
- `POST /api/system/mqtt/generic-users/{principal_id}/revoke`

Rotate credentials:
- `POST /api/system/mqtt/generic-users/{principal_id}/rotate-credentials`

Implemented policy boundary:
- allow scope for users API: `external/<username>/#`
- deny scope for generic users includes `synthia/#`
- generic users cannot keep reserved Synthia topic families in effective access

## Noisy-Client State and Actions

List noisy clients:
- `GET /api/system/mqtt/noisy-clients`

Apply noisy action:
- `POST /api/system/mqtt/noisy-clients/{principal_id}/actions/{action}`

Implemented actions:
- `mark_watch` / `watch`
- `mark_noisy` / `noisy`
- `quarantine`
- `block`
- `clear` / `clear_noisy`
- `revoke_credentials` / `rotate_credentials`

Implemented semantics:
- `quarantine` sets `status=probation` and `noisy_state=blocked`
- `block` sets `status=revoked` and `noisy_state=blocked`
- `clear` resets noisy state to `normal`; probation principals are promoted back to `active`
- rotate credentials uses configured credential rotate hook when available

Automated noisy evaluation:
- evaluator module: `backend/app/system/mqtt/noisy_clients.py`
- updates principal noisy state from runtime counters + denied-topic attempts
- does not auto-block principals

## Recovery Flow

1. Inspect degraded reason via `/mqtt/setup-summary`.
2. Review runtime/apply history in:
   - `/api/system/mqtt/audit`
   - `/api/system/mqtt/observability`
3. Reconcile runtime authority:
   - `POST /api/system/mqtt/reload`
4. Re-check degraded status and bootstrap publish readiness.
5. Validate principal effective access for impacted identities.

If runtime remains degraded after reload, use `reconciliation.last_reconcile_error`, `health.last_error`, and audit event payloads for root-cause isolation.

## Runtime Control Operations

Runtime control endpoints (admin token required):
- `GET /api/system/mqtt/runtime/health`
- `POST /api/system/mqtt/runtime/init`
- `POST /api/system/mqtt/runtime/start`
- `POST /api/system/mqtt/runtime/stop`
- `POST /api/system/mqtt/runtime/rebuild`
- `POST /api/system/mqtt/setup/apply`
- `POST /api/system/mqtt/setup/test-connection`

Implemented semantics:
- `init`: triggers authority reconcile (`reason=api_runtime_init`), ensures runtime is running, and if runtime reports `degraded_reason=config_missing` performs one reconcile+retry (`reason=api_runtime_init_config_missing`) before restarting Core MQTT client connection.
- `start`: ensures broker runtime process is running, and if runtime reports `degraded_reason=config_missing` performs one reconcile+retry (`reason=api_runtime_start_config_missing`) before restarting Core MQTT client connection.
- `stop`: stops broker runtime process and stops Core MQTT client connection.
- `rebuild`: triggers authority reconcile (`reason=api_runtime_rebuild`) and validates runtime health.
- `health`: returns runtime provider state/health and current MQTT manager connection status.
- `setup/apply`: persists selected MQTT mode/settings, initializes local runtime through reconcile/ensure-running path, retries once on `config_missing` (`reason=api_setup_apply_local_config_missing`), or validates external endpoint reachability and updates setup state.
- `setup/test-connection`: runs a lightweight endpoint reachability test for external broker setup flow without marking setup complete.

Local setup/apply enforced order:
1. persist selected setup settings
2. reconcile artifacts (without final setup-state mutation/bootstrap publish)
3. ensure runtime is running (with config-missing reconcile retry)
4. publish bootstrap after runtime healthy
5. mark setup state ready/degraded

Bootstrap publish guard:
- `ensure_bootstrap_published` now checks runtime health before publishing and skips publish when runtime is unhealthy.

Audit trail:
- runtime actions append `event_type=mqtt_runtime_control` entries in `/api/system/mqtt/audit`.

### Pipeline Ordering Audit (Task 320)

Current local setup call path (`POST /api/system/mqtt/setup/apply`):

```text
UI setup action
  -> /api/system/mqtt/setup/apply
    -> persist mqtt.mode + mqtt.<mode>.* settings
    -> reconcile_authority(reason=api_setup_apply_local)
      -> compile ACL + render broker files
      -> apply_pipeline.apply(artifacts)
        -> write temp staged dir (system temp)
        -> backup live dir
        -> promote temp staged -> live dir
        -> runtime.reload()
        -> runtime.controlled_restart() when reload unhealthy
    -> runtime.ensure_running()
      -> (if config_missing) reconcile_authority(reason=api_setup_apply_local_config_missing)
      -> runtime.ensure_running() retry once
    -> manager.restart() when initialize=true and runtime healthy
    -> update setup state ready/degraded
```

Current startup/runtime init paths:

```text
Core startup -> reconcile_startup()
  -> reconcile_authority(reason=startup)
  -> apply_pipeline.apply(...)
  -> runtime reload/restart inside pipeline
  -> publish bootstrap only when authority_ready=true

POST /api/system/mqtt/runtime/init
  -> reconcile_authority(reason=api_runtime_init)
  -> runtime.ensure_running()
  -> config_missing retry reconcile + ensure_running
  -> manager.restart() when runtime healthy
```

Observed divergence vs strict staged/live intent:
- The apply pipeline stages into an OS temp directory, not a persistent `var/mqtt_runtime/staged/` path.
- Runtime start is currently protected by reconcile before `ensure_running`, but there is no explicit persistent staged artifact contract yet.

Expected strict order target:

```text
1) persist setup state
2) render broker config
3) write artifacts to var/mqtt_runtime/staged/
4) atomically promote staged -> live
5) run reconcile
6) ensure runtime running
7) publish bootstrap
8) mark setup complete
```

Addon UI mapping:
- `/addons/mqtt` Runtime section now exposes buttons for `Init`, `Start`, `Stop`, `Rebuild`, and `Check Health`, wired to the endpoints above.
- `/addons/mqtt` post-setup navigation sections:
  - Overview: setup/runtime/authority/bootstrap summary
  - Principals: principal list with type/status filters, topic-prefix visibility, and generic-user actions (revoke/disable/rotate)
  - Generic Users: broker-user list with status filter and Add User workflow shortcut
  - Runtime: runtime details + runtime control actions
  - Audit: authority/runtime audit history with result filters
  - Noisy Clients: noisy-state visibility with state filter
- Setup gating behavior:
  - when `setup_complete=false` and `requires_setup=true`, only Setup section is available
  - once setup completes, post-setup sections unlock automatically
- Principals API/system visibility:
  - `GET /api/system/mqtt/principals` includes Core system principals:
    - `core.scheduler`
    - `core.supervisor`
    - `core.telemetry`
    - `core.runtime`
    - `core.bootstrap`
  - system principals are marked with `principal_type=system` and `managed_by=core`
  - startup reconciliation recreates missing Core system principals automatically
  - Add User workflow:
    - open from Principals or Generic Users section
    - submits `username/password/topic_prefix` to `POST /api/system/mqtt/users`
    - refreshes principals after create

## Docker Runtime Operations (Local Mode)

Runtime files:
- staged rendered config/auth/ACL: `var/mqtt_runtime/staged/*`
- live rendered config/auth/ACL: `var/mqtt_runtime/live/*`
- data: `var/mqtt_runtime/data/*`
- logs: `var/mqtt_runtime/logs/*`
- Core startup bootstrap guarantees these runtime directories exist on fresh installs.

Container behavior:
- Core starts broker container with host networking and mounts runtime paths.
- Core health checks combine container running state + TCP reachability.
- `reload` uses Docker signal flow (`HUP`) and keeps container identity stable.
- `controlled_restart` uses stop/remove + fresh start path.
- Runtime preflight validates required live artifacts before broker start:
  - `live/broker.conf`
  - `live/acl_compiled.conf`
  - `live/passwords.conf`
  If missing, runtime start is rejected with `config_missing:*` including:
  - expected live broker config path
  - staged broker config existence flag
  - live directory existence flag
  - missing artifact list
  - suggestion to run setup apply/rebuild

Failure and recovery:
1. Check setup/runtime summary: `GET /api/system/mqtt/setup-summary`
2. Check runtime endpoint: `GET /api/system/mqtt/runtime/health`
3. Trigger controlled path:
   - `POST /api/system/mqtt/runtime/rebuild` (preferred)
   - or `POST /api/system/mqtt/runtime/start`
4. Supervisor self-heal path:
   - runtime supervision loop performs reconcile+retry when runtime health remains degraded with `config_missing` (`reason=runtime_supervisor_config_missing`)
5. Re-check `effective_status`, runtime health, and bootstrap publish status.

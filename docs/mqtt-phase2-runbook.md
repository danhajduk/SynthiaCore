# MQTT Embedded Phase 2 Runbook

Last Updated: 2026-03-10 02:14 US/Pacific

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

## Generic User Lifecycle

Create or update generic user:
- `POST /api/system/mqtt/generic-users`

Update grants:
- `PATCH /api/system/mqtt/generic-users/{principal_id}/grants`

Revoke generic user:
- `POST /api/system/mqtt/generic-users/{principal_id}/revoke`

Rotate credentials:
- `POST /api/system/mqtt/generic-users/{principal_id}/rotate-credentials`

Implemented policy boundary:
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
- `init`: triggers authority reconcile (`reason=api_runtime_init`), ensures runtime is running, then restarts Core MQTT client connection.
- `start`: ensures broker runtime process is running, then restarts Core MQTT client connection.
- `stop`: stops broker runtime process and stops Core MQTT client connection.
- `rebuild`: triggers authority reconcile (`reason=api_runtime_rebuild`) and validates runtime health.
- `health`: returns runtime provider state/health and current MQTT manager connection status.
- `setup/apply`: persists selected MQTT mode/settings, initializes local runtime through reconcile/ensure-running path, or validates external endpoint reachability and updates setup state.
- `setup/test-connection`: runs a lightweight endpoint reachability test for external broker setup flow without marking setup complete.

Audit trail:
- runtime actions append `event_type=mqtt_runtime_control` entries in `/api/system/mqtt/audit`.

Addon UI mapping:
- `/addons/mqtt` Runtime section now exposes buttons for `Init`, `Start`, `Stop`, `Rebuild`, and `Check Health`, wired to the endpoints above.

## Docker Runtime Operations (Local Mode)

Runtime files:
- live rendered config/auth/ACL: `var/mqtt_runtime/live/*`
- data: `var/mqtt_runtime/data/*`
- logs: `var/mqtt_runtime/logs/*`

Container behavior:
- Core starts broker container with host networking and mounts runtime paths.
- Core health checks combine container running state + TCP reachability.
- `reload` uses Docker signal flow (`HUP`) and keeps container identity stable.
- `controlled_restart` uses stop/remove + fresh start path.

Failure and recovery:
1. Check setup/runtime summary: `GET /api/system/mqtt/setup-summary`
2. Check runtime endpoint: `GET /api/system/mqtt/runtime/health`
3. Trigger controlled path:
   - `POST /api/system/mqtt/runtime/rebuild` (preferred)
   - or `POST /api/system/mqtt/runtime/start`
4. Re-check `effective_status`, runtime health, and bootstrap publish status.

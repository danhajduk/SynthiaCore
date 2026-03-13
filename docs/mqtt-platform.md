# MQTT Platform

## Purpose

Status: Implemented (embedded authority/runtime foundation), Partial (future automation/federation)

Synthia's MQTT platform provides Core-owned authority state, principal lifecycle controls, topic policy boundaries, and embedded broker runtime management.

## Authority Model

Status: Implemented

- Core persists authority/principal state and setup readiness.
- Approval/provision/revoke and lifecycle actions are API-driven and audited.
- Generic users are constrained away from reserved platform topic families.

Key modules:
- `backend/app/system/mqtt/approval.py`
- `backend/app/system/mqtt/integration_state.py`
- `backend/app/system/mqtt/effective_access.py`
- `backend/app/system/mqtt/authority_audit.py`

## Embedded Runtime Model

Status: Implemented

- Runtime boundary abstraction supports docker-backed runtime (default) and memory fallback.
- Core supervision loop performs health checks, recovery attempts, and config-missing reconciliation.

Key modules:
- `backend/app/system/mqtt/runtime_boundary.py`
- `backend/app/system/mqtt/manager.py`
- `backend/app/system/mqtt/startup_reconcile.py`
- `backend/app/system/mqtt/apply_pipeline.py`

## Bootstrap

Status: Implemented

- Startup reconciliation ensures authority/runtime alignment and bootstrap publish state.
- Bootstrap publish endpoints and summary status are exposed for operator control.
- Published bootstrap payload includes `topic`, `bootstrap_version`, `core_id`, `core_name`, `core_version`, `api_base`, `mqtt_host`, `mqtt_port`, `onboarding_endpoints`, `onboarding_mode`, `onboarding_contract`, `compatibility`, and `emitted_at`.
- Current onboarding registration advertisement includes:
  - `onboarding_endpoints.register_session=/api/system/nodes/onboarding/sessions`
  - `onboarding_endpoints.registrations=/api/system/nodes/registrations`
  - compatibility keys for legacy consumers (`register`, `ai_node_register`)

## Topics

Status: Implemented (canonical reserved families), Partial (future family expansion)

- Reserved platform families (`synthia/core`, `synthia/system`, `synthia/scheduler`, `synthia/supervisor`, `synthia/policy`, `synthia/telemetry`) are protected.
- Addon topics are scoped under `synthia/addons/<addon_id>/...`.
- Node and service visibility topic families are represented in current topic-tree contract.

## Notification Contract

Status: Implemented (canonical shared schema), Partial (publishers/consumers still expanding)

- Core exposes a shared notification schema module for MQTT notification envelopes at `backend/app/core/notifications.py`.
- Core exposes a reusable MQTT notification publisher utility at `backend/app/core/notification_publisher.py` and wires it on app state as `notification_publisher`.
- Core exposes a local desktop notification consumer at `backend/app/core/notification_consumer.py` and wires it on app state as `notification_consumer`.
- Core emits startup smoke-test notifications through `backend/app/core/notification_producer.py` after MQTT startup/reconcile completes.
- Canonical internal topics are `synthia/notify/internal/event`, `synthia/notify/internal/state`, and `synthia/notify/internal/popup`.
- External bridge targets should derive downstream topics via `synthia/notify/external/<target>` using the shared topic helper.
- The shared contract validates target scope, payload presence, optional TTL expiry, and reusable JSON serialization/parsing for future Core, addon, and node notification producers/consumers.
- The publisher validates payloads before publish, omits empty optional sections with `exclude_none`, keeps popup/event notifications non-retained, and only allows retained state notifications when explicitly requested.
- Current startup smoke-test production emits one popup, one event, and one retained ready-state notification with structured emission logs.
- The desktop consumer listens for internal popup and event topics, validates canonical payloads, drops invalid or expired notifications, matches local user/host/session or broadcast targets, deduplicates by `dedupe_key`, and uses `notify-send` for local desktop display when available.

## Principals and Users

Status: Implemented

- Principal listing/details and lifecycle actions are exposed via admin endpoints.
- Generic users support create/update/delete/rotate/export/import and effective-access inspection.
- System principals and addon principals are visible in principal APIs and UI.

## ACL / Compiler Model

Status: Implemented

- Effective-access normalization feeds deterministic ACL rendering.
- Debug endpoints expose raw and normalized effective-access output and generated config.
- Reserved-topic protection and deny dedupe are enforced in compilation path.

## Startup / Apply / Reconcile

Status: Implemented

- Setup apply flow can stage, promote, and activate runtime artifacts.
- Reconcile hooks run on startup and on authority/lifecycle changes.
- Runtime rebuild/start/stop/init and health routes are exposed for operational workflows.

## Observability

Status: Implemented

- Observability store tracks runtime events, denied-topic activity, and health telemetry.
- Noisy-client evaluator tracks state and supports manual action workflows.

## Runbook Notes

Status: Implemented

- Operators should validate setup summary, runtime health, and recent audit/observability events before applying changes.
- Rebuild may be force-gated when active non-core clients are connected.

## Future Phases

Status: Planned

- Additional federation/import topic families and policy automation.
- Broader noisy-client automated mitigation policies.
- More strict envelope/schema enforcement across all MQTT message families.

## API Surface Snapshot

Status: Implemented

Representative routes under `/api/system`:
- `/mqtt/status`, `/mqtt/setup-summary`, `/mqtt/health`
- `/mqtt/setup/apply`, `/mqtt/setup/test-connection`, `/mqtt/setup-state`
- `/mqtt/runtime/*` and compatibility aliases `/runtime/*`
- `/mqtt/principals*`, `/mqtt/users*`, `/mqtt/generic-users*`
- `/mqtt/noisy-clients*`, `/mqtt/audit`, `/mqtt/observability`
- `/mqtt/debug/*`

## Legacy Note

Status: Archived Legacy

- Previous split MQTT docs (`mqtt-contract`, runtime boundary notes, topic gap notes, phase runbooks, blueprint docs) have been consolidated and archived.

## See Also

- [API Reference](./api-reference.md)
- [Operators Guide](./operators-guide.md)
- [Auth and Identity](./auth-and-identity.md)
- [Data and State](./data-and-state.md)
- [Runtime and Supervision](./runtime-and-supervision.md)

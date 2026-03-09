# MQTT Integration Contract

Last Updated: 2026-03-09 06:37 US/Pacific

## Scope

This document describes MQTT integration behavior currently implemented in Core code.

Target-direction references for embedded platform-managed MQTT:
- [MQTT Embedded Migration Gap Note](./mqtt-embedded-gap-note.md)
- [MQTT Embedded Architecture (Target)](./mqtt-embedded-architecture.md)
- [MQTT Embedded Addon/Platform Contract](./mqtt-embedded-contract.md)
- [MQTT Bootstrap Contract](./mqtt-bootstrap-contract.md)
- [MQTT Authority Persistence Model](./mqtt-authority-persistence.md)
- [MQTT Broker Runtime Boundary](./mqtt-runtime-boundary.md)
- [MQTT Startup Reconciliation](./mqtt-startup-reconciliation.md)
- [MQTT Apply and Rollback Pipeline](./mqtt-apply-rollback.md)

## Control-Plane vs Event-Plane

Implemented:
- Deterministic control operations use HTTP APIs (`/api/system/mqtt/*` and policy/admin APIs).
- MQTT topics are used for asynchronous visibility and retained policy distribution.

Not developed:
- Primary control transactions over MQTT topics.

## Reserved Namespaces

Core validates reserved platform namespaces in topic approval logic (`backend/app/system/mqtt/topic_policy.py`):
- `synthia/system/...`
- `synthia/core/...`
- `synthia/supervisor/...`
- `synthia/scheduler/...`
- `synthia/policy/...`
- `synthia/telemetry/...`

Addon publish topics must remain under:
- `synthia/addons/<addon_id>/...`

Embedded authority policy foundations:
- Synthia principals may access approved reserved trees.
- Generic users are denied reserved trees.
- Anonymous is restricted to bootstrap-only subscription.

## Lifecycle and Platform Topics

Core subscribes (QoS 1) to:
- `synthia/core/mqtt/info`
- `synthia/addons/+/announce`
- `synthia/addons/+/health`
- `synthia/services/+/catalog`
- `synthia/policy/grants/+`
- `synthia/policy/revocations/+`

Core publishes:
- `synthia/core/mqtt/info` (retained, QoS 1) on connect/restart.
- policy grants to `synthia/policy/grants/{service}` (retained, QoS 1).
- policy revocations to:
  - `synthia/policy/revocations/{consumer_addon_id}` (when present, retained, QoS 1)
  - `synthia/policy/revocations/{grant_id}` (when present, retained, QoS 1)
  - `synthia/policy/revocations/{id}` legacy compatibility path (retained, QoS 1)

## Registration and Approval Model

Implemented registration/approval APIs:
- `GET /api/system/mqtt/status`
- `POST /api/system/mqtt/test`
- `POST /api/system/mqtt/restart`
- `POST /api/system/mqtt/registrations/approve`
- `POST /api/system/mqtt/registrations/{addon_id}/provision`
- `POST /api/system/mqtt/registrations/{addon_id}/revoke`
- `GET /api/system/mqtt/grants`
- `GET /api/system/mqtt/grants/{addon_id}`
- `GET /api/system/mqtt/setup-summary`
- `POST /api/system/mqtt/setup-state`

Behavior:
- Core validates addon existence/enabled state and topic policy before approval.
- Core persists grant state and principal authority outcomes in Core-owned state.
- Provision/revoke endpoints apply embedded authority state transitions (no remote addon HTTP provisioning dependency).
- Grant apply is gated on setup readiness when setup is required.

Setup summary compatibility:
- Preferred error aggregation key: `last_authority_errors`
- Compatibility alias preserved: `last_provisioning_errors`

Embedded authority foundations:
- ACL compiler module: `backend/app/system/mqtt/acl_compiler.py`
- Broker config renderer: `backend/app/system/mqtt/config_renderer.py`
- Runtime boundary interface: `backend/app/system/mqtt/runtime_boundary.py`
- Startup reconcile service: `backend/app/system/mqtt/startup_reconcile.py`
- Apply/rollback service: `backend/app/system/mqtt/apply_pipeline.py`
- Audit store: `backend/app/system/mqtt/authority_audit.py`
- Observability store: `backend/app/system/mqtt/observability_store.py`

Embedded API semantics:
- `/mqtt/registrations/{addon_id}/provision` applies Core authority state (no remote addon provisioning HTTP dependency).
- `/mqtt/registrations/{addon_id}/revoke` revokes Core authority state.
- `/mqtt/reload` is available as embedded runtime reload alias.
- `/mqtt/health` returns effective degraded/healthy summary.

## JSON Envelope Requirement

Implemented:
- Core MQTT publish paths serialize payloads as JSON objects.
- Secret-like fields are redacted before publish via `redact_secrets`.

Not developed:
- A globally enforced MQTT envelope schema (for example `spec_version/message_type/source/...`) validated for all inbound/outbound topics.

## Retain and QoS Defaults

Implemented defaults in current code paths:
- Core info topic publish: retained `true`, QoS `1`.
- Policy grant/revocation publish: retained `true`, QoS `1`.
- Generic `MqttManager.publish` defaults: retained `true`, QoS `1`.

Not developed:
- System-wide per-topic QoS policy registry.

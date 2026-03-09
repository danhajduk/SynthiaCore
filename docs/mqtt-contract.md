# MQTT Integration Contract

Last Updated: 2026-03-09 06:36 US/Pacific

## Scope

This document describes MQTT integration behavior currently implemented in Core code.

Target-direction references for embedded platform-managed MQTT:
- [MQTT Embedded Migration Gap Note](./mqtt-embedded-gap-note.md)
- [MQTT Embedded Architecture (Target)](./mqtt-embedded-architecture.md)
- [MQTT Embedded Addon/Platform Contract](./mqtt-embedded-contract.md)

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
- Core persists grant state and provisioning/revocation outcomes.
- Provisioning is gated on setup readiness when setup is required.

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

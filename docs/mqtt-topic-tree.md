# Synthia MQTT Topic Tree (Canonical)

Last Updated: 2026-03-10 07:18 US/Pacific

## Contract

This document is the canonical topic-structure source of truth for Synthia MQTT in this repository.

Control-plane rule:
- MQTT topics are async visibility/distribution transport.
- Deterministic control transactions remain HTTP API-first.

## Top-Level Reserved Families

| Family | Owner | Phase 1 Status | Notes |
|---|---|---|---|
| `synthia/bootstrap/...` | Core | Implemented (core bootstrap topic) | Anonymous bootstrap-only subscribe contract |
| `synthia/runtime/...` | Core Platform | Reserved | Runtime state/health/config family |
| `synthia/core/...` | Core | Partially Implemented | `synthia/core/mqtt/info` implemented |
| `synthia/system/...` | Core Platform | Reserved | Protected namespace |
| `synthia/supervisor/...` | Core Platform | Reserved | Protected namespace |
| `synthia/scheduler/...` | Core Platform | Reserved | Protected namespace |
| `synthia/policy/...` | Core Policy | Implemented | Grant/revocation distribution topics implemented |
| `synthia/telemetry/...` | Core Platform | Reserved | Protected namespace |
| `synthia/events/...` | Core Platform | Reserved | Shared platform event-visibility root (reserved) |
| `synthia/remote/...` | Core Platform | Reserved | Future federation/remote family |
| `synthia/bridges/...` | Core Platform | Reserved | Future bridge family |
| `synthia/import/...` | Core Platform | Reserved | Future import family |
| `synthia/services/...` | Core Services | Partially Implemented | `synthia/services/+/catalog` subscription implemented |
| `synthia/addons/<addon_id>/...` | Addon Principal + Core policy | Implemented (announce/health + scoped publish rules) | Addon publish must stay in addon namespace unless explicitly approved reserved access |
| `synthia/nodes/<node_id>/...` | Synthia Node Principal | Not developed | Reserved planned family for Phase 1+ |

## Family Contracts

### Core Operational Family (`synthia/core/...`)

Implemented:
- `synthia/core/mqtt/info` retained Core visibility topic.

Planned/Not developed:
- `synthia/core/status/...`
- `synthia/core/health/...`
- `synthia/core/events/...`

Boundary:
- deterministic Core control actions remain HTTP APIs.

### Runtime Family (`synthia/runtime/...`)

Reserved runtime subtree targets:
- `synthia/runtime/status`
- `synthia/runtime/health`
- `synthia/runtime/broker/...`
- `synthia/runtime/config/...`

Status:
- reserved/partially implemented for platform runtime visibility; do not grant to generic users.

### Addon Family (`synthia/addons/<addon_id>/...`)

Implemented:
- `synthia/addons/<addon_id>/announce`
- `synthia/addons/<addon_id>/health`

Approved subtree direction:
- `synthia/addons/<addon_id>/events/...`
- `synthia/addons/<addon_id>/status/...`
- `synthia/addons/<addon_id>/telemetry/...`

Policy boundary:
- addon publish must remain under addon namespace unless Core explicitly grants reserved access.

### Node Family (`synthia/nodes/<node_id>/...`)

Phase 1 planned (Not developed):
- status
- events
- telemetry
- health

Boundary:
- reserved for Core-approved Synthia node principals only.

### Services Family (`synthia/services/...`)

Implemented:
- `synthia/services/+/catalog` subscription family.

Planned/Not developed:
- `synthia/services/<service>/health`
- `synthia/services/<service>/status`

Boundary:
- informational/async visibility topics only.

### Policy Family (`synthia/policy/...`)

Implemented:
- `synthia/policy/grants/{service}`
- `synthia/policy/revocations/{consumer_addon_id}`
- `synthia/policy/revocations/{grant_id}`
- `synthia/policy/revocations/{id}` (legacy compatibility)

Defaults:
- retained `true`
- QoS `1`

Boundary:
- policy topics distribute visibility/state artifacts; approval/revoke control remains API-driven.

### Telemetry Family (`synthia/telemetry/...`)

Reserved platform family in Phase 1.

Boundary:
- platform-level telemetry topics belong here.
- addon-local telemetry should use addon-scoped subtree (`synthia/addons/<id>/telemetry/...`).

### System / Supervisor / Scheduler Families

Reserved ownership:
- `synthia/system/...`
- `synthia/supervisor/...`
- `synthia/scheduler/...`
- `synthia/events/...` (shared platform visibility root)
- `synthia/remote/...` (future federation)
- `synthia/bridges/...` (future bridging)
- `synthia/import/...` (future imported traffic)

Boundary:
- reserved for platform-owned semantics.
- avoid mixed-purpose catch-all trees.
- treat unimplemented subtrees as reserved, not open.

## Implemented Lifecycle/Platform Topics

| Topic | Publisher | Subscriber(s) | Retained | QoS | Status |
|---|---|---|---|---|---|
| `synthia/bootstrap/core` | Core startup reconcile | Anonymous + platform clients | `true` | `1` | Implemented |
| `synthia/core/mqtt/info` | Core MQTT manager/startup reconcile | Core + observers | `true` | `1` | Implemented |
| `synthia/addons/+/announce` | Addons | Core MQTT manager | producer-defined | `1` (Core subscription) | Implemented |
| `synthia/addons/+/health` | Addons | Core MQTT manager | producer-defined | `1` (Core subscription) | Implemented |
| `synthia/services/+/catalog` | Services | Core MQTT manager | producer-defined | `1` (Core subscription) | Implemented |
| `synthia/policy/grants/{service}` | Core policy | Consumers/services | `true` | `1` | Implemented |
| `synthia/policy/revocations/{consumer_addon_id}` | Core policy | Consumers/services | `true` | `1` | Implemented |
| `synthia/policy/revocations/{grant_id}` | Core policy | Consumers/services | `true` | `1` | Implemented |
| `synthia/policy/revocations/{id}` (legacy) | Core policy | Legacy consumers | `true` | `1` | Implemented |

## Bootstrap/Discovery Family

Canonical bootstrap topic:
- `synthia/bootstrap/core`

Contract:
- Payload model: `MqttBootstrapAnnouncement` (`backend/app/system/mqtt/integration_models.py`)
- Retained: `true`
- QoS: `1`
- Publisher owner: Core embedded startup reconcile (`startup_reconcile.py`)
- Allowed anonymous access:
  - subscribe only to exact bootstrap topic
  - no publish
  - no wildcard subscribe

## Reserved-Family Access Rules (Phase 1)

- Synthia principals (`synthia_addon`, `synthia_node`) may access reserved topics only with explicit Core approval.
- Generic users cannot access reserved families by default.
- Anonymous clients are limited to bootstrap-only subscribe.

## Topic Ownership Matrix

| Family | Owner | Allowed Publishers | Allowed Subscribers | Retained Default | QoS Default | Implementation |
|---|---|---|---|---|---|---|
| `synthia/bootstrap/...` | Core | Core | Anonymous, Synthia principals, generic users | `true` for `synthia/bootstrap/core` | `1` | Implemented (`core` topic) |
| `synthia/runtime/...` | Core Platform | Core/runtime services | Core/platform services | topic-specific | topic-specific | Reserved |
| `synthia/core/...` | Core | Core | Core + platform observers | `true` for `synthia/core/mqtt/info` | `1` | Partially Implemented |
| `synthia/system/...` | Core Platform | Core platform services | Core platform services | topic-specific | topic-specific | Reserved |
| `synthia/supervisor/...` | Core Platform | Core/supervisor services | Core/supervisor services | topic-specific | topic-specific | Reserved |
| `synthia/scheduler/...` | Core Platform | Core/scheduler services | Core/scheduler services | topic-specific | topic-specific | Reserved |
| `synthia/policy/...` | Core Policy | Core policy publisher | Policy consumers, Core | `true` | `1` | Implemented |
| `synthia/telemetry/...` | Core Platform | Core platform telemetry producers | Core/platform consumers | topic-specific | topic-specific | Reserved |
| `synthia/events/...` | Core Platform | Core/platform services | Core/platform services | topic-specific | topic-specific | Reserved |
| `synthia/remote/...` | Core Platform | Core federation services | Core federation services | topic-specific | topic-specific | Reserved |
| `synthia/bridges/...` | Core Platform | Core bridge services | Core bridge services | topic-specific | topic-specific | Reserved |
| `synthia/import/...` | Core Platform | Core import services | Core import services | topic-specific | topic-specific | Reserved |
| `synthia/services/...` | Core Services | Service publishers (catalog implemented) | Core service catalog consumer | producer-defined | `1` (Core subscription) | Partially Implemented |
| `synthia/addons/<addon_id>/...` | Addon + Core policy | Matching addon principal (and Core when required) | Core + authorized clients | producer-defined | `1` (announce/health subscriptions) | Implemented/Scoped |
| `synthia/nodes/<node_id>/...` | Node + Core policy | Core-approved node principal | Core + authorized clients | topic-specific | topic-specific | Not developed |

Principal-role summary for Phase 1:
- Core: platform publisher/subscriber as defined above.
- Synthia addon principals: allowed in addon scope and explicitly approved reserved access.
- Synthia node principals: planned under node family; reserved policy applies.
- Generic users: denied reserved families by default.
- Anonymous clients: subscribe-only to `synthia/bootstrap/core`; no publish/wildcards.

## Not Developed

- Node topic family runtime usage (`synthia/nodes/<node_id>/...`).
- Additional Core operational topic subtrees:
  - `synthia/core/status/...`
  - `synthia/core/health/...`
  - `synthia/core/events/...`
- Additional service visibility topic set beyond `synthia/services/+/catalog`.

## Phase 1 TODO Markers

- TODO(phase1-topic): implement runtime usage and validation semantics for `synthia/nodes/<node_id>/...`.
- TODO(phase1-topic): implement additional Core visibility subtrees (`status`, `health`, `events`) when concrete producers/consumers are defined.
- TODO(phase1-topic): evaluate additional `synthia/services/<service>/(health|status)` topics once service-side producers are implemented.

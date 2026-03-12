# Node Phase 2 Lifecycle Contract

Status: Implemented
Last Updated: 2026-03-11 17:07

## Purpose

Defines the implemented Core-side Phase 2 lifecycle contract after node trust activation:

- capability declaration
- capability profile persistence
- governance issuance and refresh
- operational readiness state
- runtime telemetry ingestion

## Readiness Model

`operational_ready` is `true` only when all are true:

1. `trust_status == trusted`
2. `capability_status == accepted`
3. `governance_sync_status == issued`

Derived status fields exposed by node registry and operational-status APIs:

- `capability_status`: `missing | declared | accepted`
- `governance_sync_status`: `pending_capability | pending | issued`
- `operational_ready`: boolean
- `active_governance_version`: current governance version (or `null`)
- `governance_last_issued_at`: timestamp (or `null`)
- `governance_last_refresh_request_at`: timestamp (or `null`)

## API Contract

### Capability Declaration

- `POST /api/system/nodes/capabilities/declaration`
- Auth: `X-Node-Trust-Token`
- Request:
  - `manifest.manifest_version`
  - `manifest.node.node_id`
  - `manifest.node.node_type`
  - `manifest.node.node_name`
  - `manifest.node.node_software_version`
  - `manifest.declared_task_families[]`
  - `manifest.supported_providers[]`
  - `manifest.enabled_providers[]`
  - `manifest.node_features.telemetry`
  - `manifest.node_features.governance_refresh`
  - `manifest.node_features.lifecycle_events`
  - `manifest.node_features.provider_failover`
  - `manifest.environment_hints.deployment_target`
  - `manifest.environment_hints.acceleration`
  - `manifest.environment_hints.network_tier`
  - `manifest.environment_hints.region`
- Success response:
  - `acceptance_status: accepted`
  - `node_id`
  - `manifest_version`
  - `accepted_at`
  - `declared_capabilities[]`
  - `enabled_providers[]`
  - `capability_profile_id`
  - `governance_version`
  - `governance_issued_at`

### Capability Profile Registry

- `GET /api/system/nodes/capabilities/profiles?node_id=...` (admin auth)
- `GET /api/system/nodes/capabilities/profiles/{profile_id}` (admin auth)
- Returns immutable accepted profile records including normalized capability fields and `declaration_raw`.

### Governance Bundle Fetch

- `GET /api/system/nodes/governance/current?node_id=...`
- Auth: `X-Node-Trust-Token`
- Requires trusted node and accepted capability profile.
- Success response:
  - `node_id`
  - `capability_profile_id`
  - `governance_version`
  - `issued_timestamp`
  - `refresh_interval_s`
  - `governance_bundle` (versioned baseline contract)

### Governance Refresh

- `POST /api/system/nodes/governance/refresh`
- Auth: `X-Node-Trust-Token`
- Request:
  - `node_id`
  - `current_governance_version` (optional)
- Response when changed:
  - `updated: true`
  - `governance_version`
  - `governance_bundle`
  - `refresh_interval_s`
- Response when unchanged:
  - `updated: false`
  - `governance_version`
  - `refresh_interval_s`

### Operational Status

- `GET /api/system/nodes/operational-status/{node_id}`
- Auth: either `X-Node-Trust-Token` or admin auth/session.
- Response:
  - `node_id`
  - `lifecycle_state`
  - `trust_status`
  - `capability_status`
  - `governance_status`
  - `operational_ready`
  - `active_governance_version`
  - `last_governance_issued_at`
  - `last_governance_refresh_request_at`
  - `last_telemetry_timestamp`
  - `updated_at`

### Telemetry Ingestion

- `POST /api/system/nodes/telemetry`
- Auth: `X-Node-Trust-Token`
- Request:
  - `node_id`
  - `event_type` (allowed: `lifecycle_transition`, `degraded_state`, `capability_declaration_success`, `governance_sync`)
  - `event_state` (optional)
  - `message` (optional)
  - `payload` (optional, lightweight JSON object)
- Success response:
  - `node_id`
  - `event_type`
  - `received_at`

## See Also

- [Node Capability Activation Architecture (Phase 2)](./node-capability-activation-architecture.md)
- [API Reference](./api-reference.md)
- [Node Onboarding Phase 1 Contract](./node-onboarding-phase1-contract.md)

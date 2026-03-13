# Node Onboarding Phase 1 Contract

Status: Implemented (current runtime behavior)
Last updated: 2026-03-11

## Scope

Defines the implemented Phase 1 contract for:

- bootstrap discovery for node onboarding
- operator approval flow
- trust activation payload issuance
- registry and lifecycle state transitions
- MQTT principal representation for onboarded nodes

This document reflects current code behavior only.

## Bootstrap Discovery Contract

Core publishes retained bootstrap metadata to:

- topic: `synthia/bootstrap/core`

Payload includes:

- `onboarding_endpoints.register_session=/api/system/nodes/onboarding/sessions`
- `onboarding_endpoints.registrations=/api/system/nodes/registrations`
- `onboarding_endpoints.register` and `onboarding_endpoints.ai_node_register` for legacy compatibility
- `onboarding_mode=api`
- `onboarding_contract=global-node-v1`

Publication cadence:

- startup reconciliation publishes bootstrap
- runtime supervision loop forces republish every 30 seconds while MQTT runtime is healthy

## Approval Contract

Node starts onboarding:

- `POST /api/system/nodes/onboarding/sessions`

Operator decision:

- `GET /api/system/nodes/onboarding/sessions/{session_id}?state=...`
- `POST /api/system/nodes/onboarding/sessions/{session_id}/approve?state=...`
- `POST /api/system/nodes/onboarding/sessions/{session_id}/reject?state=...`

UI behavior:

- approval popup closes after approve/reject
- popup posts `synthia.node_onboarding.decided` message to opener
- parent settings view refreshes onboarding session state on that message

## Identity And Registration Contract

Node identity is derived from `node_nonce`:

- `node_id = node-<sha256(node_nonce)[:16]>`

Phase 1 uniqueness rule:

- duplicate active session by same `node_nonce` is rejected
- duplicate identity when same derived `node_id` already exists is rejected

Registration APIs:

- `GET /api/system/nodes/registrations`
- `GET /api/system/nodes/registrations/{node_id}`
- `GET /api/system/nodes/registry` (normalized view model)

Registry states:

- `pending`
- `approved`
- `trusted`
- `revoked`

## Trust Activation Contract

Node finalization:

- `GET /api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=...`

On approved finalization, Core issues activation payload with:

- `node_id`
- canonical `node_type`
- `paired_core_id`
- `node_trust_token`
- `operational_mqtt_identity`
- `operational_mqtt_token`
- `operational_mqtt_host`
- `operational_mqtt_port`

Approved finalization is one-time consumable per session.

## MQTT Principal Lifecycle Contract

Node principals are exposed in MQTT principal APIs as synthetic `synthia_node` principals:

- `principal_id=node:{node_id}`
- `status=active` when registry trust is `trusted`
- `status=revoked` when registry trust is `revoked`/`rejected`
- otherwise `status=pending`

Node lifecycle actions:

- revoke/untrust: `POST /api/system/nodes/registrations/{node_id}/revoke` (alias `/untrust`)
- remove node: `DELETE /api/system/nodes/registrations/{node_id}`

Both actions revoke stored node trust credential records; remove additionally deletes the registry record.

## Compatibility

Legacy onboarding alias routes remain available:

- `/api/system/ai-nodes/onboarding/sessions*`

Legacy alias responses include deprecation headers and migration warning.

## See Also

- [Node Onboarding API Contract](./node-onboarding-api-contract.md)
- [Node Trust Activation Payload Contract](./node-trust-activation-payload-contract.md)
- [Node Onboarding Migration Guide](./node-onboarding-migration-guide.md)
- [MQTT Platform](../mqtt/mqtt-platform.md)

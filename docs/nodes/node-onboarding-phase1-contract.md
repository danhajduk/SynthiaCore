# Node Onboarding Phase 1 Contract

Status: Implemented (current runtime behavior)
Last updated: 2026-03-20 10:09

## Scope

Defines the implemented Phase 1 contract for:

- bootstrap discovery for node onboarding
- operator approval flow
- trust activation payload issuance
- registry and lifecycle state transitions
- MQTT principal representation for onboarded nodes

This document reflects current code behavior only.

## Canonical Phase 1 Sequence

The canonical node onboarding sequence is:

1. `Node Identity` -> `unconfigured`
2. `Core Connection` -> `bootstrap_connecting`
3. `Bootstrap Discovery` -> `bootstrap_connected` then `core_discovered`
4. `Registration` -> `registration_pending`
5. `Approval` -> `pending_approval`
6. `Trust Activation` -> `trusted`

Phase 2 continues from trust activation with:

7. `Provider Setup`
8. `Capability Declaration`
9. `Governance Sync`
10. `Ready`

This document covers the Phase 1 steps. Phase 2 readiness is documented in [Node Phase 2 Lifecycle Contract](./node-phase2-lifecycle-contract.md).

## Bootstrap Discovery Contract

Core publishes retained bootstrap metadata to:

- topic: `hexe/bootstrap/core`

Compatibility note:

- the public-facing product name is Hexe AI / Hexe Core
- the bootstrap topic remains `hexe/bootstrap/core`

Bootstrap transport:

- bootstrap discovery is published over the embedded MQTT bootstrap listener
- default bootstrap MQTT port: `1884`
- runtime boundary default: `SYNTHIA_MQTT_BOOTSTRAP_PORT=1884`
- bootstrap listener is distinct from the normal operational MQTT listener on `1883`

Payload includes:

- `onboarding_endpoints.register_session=/api/system/nodes/onboarding/sessions`
- `onboarding_endpoints.registrations=/api/system/nodes/registrations`
- `onboarding_endpoints.register` and `onboarding_endpoints.ai_node_register` for legacy compatibility
- `onboarding_mode=api`
- `onboarding_contract=global-node-v1`

Publication cadence:

- startup reconciliation publishes bootstrap
- runtime supervision loop forces republish every 30 seconds while MQTT runtime is healthy

Phase-1 step mapping:

- `Core Connection`: node reaches the bootstrap MQTT listener and can be considered `bootstrap_connecting` or `bootstrap_connected`
- `Bootstrap Discovery`: node reads retained Core bootstrap metadata from `hexe/bootstrap/core` and can be considered `core_discovered`

## Approval Contract

Phase-1 step mapping:

- `Registration`: node starts the onboarding session with its identity metadata and enters `registration_pending`
- `Approval`: operator review corresponds to `pending_approval`

Node starts onboarding:

- `POST /api/system/nodes/onboarding/sessions`

Operator decision:

- `GET /api/system/nodes/onboarding/sessions/{session_id}?state=...`
- `POST /api/system/nodes/onboarding/sessions/{session_id}/approve?state=...`
- `POST /api/system/nodes/onboarding/sessions/{session_id}/reject?state=...`

UI behavior:

- approval popup closes after approve/reject
- popup posts `hexe.node_onboarding.decided` message to opener
- parent settings view refreshes onboarding session state on that message

## Identity And Registration Contract

Node identity rules:

- nodes may request a stable `node_id` during onboarding
- current accepted requested formats are:
  - UUIDv4 canonical text form
  - legacy `node-...` identifiers
- if a requested `node_id` is not provided, Core derives one from `node_nonce`:
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

Phase-1 step mapping:

- `Node Identity`: node provides `node_type`, node metadata, and nonce binding while still effectively `unconfigured`
- `Registration`: Core persists the onboarding session and later the registration record linked to the approved node identity

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

Phase-1 step mapping:

- `Trust Activation`: finalization consumes the approved session, returns trust material plus operational MQTT credentials, and transitions the node to `trusted`

## MQTT Principal Lifecycle Contract

Node principals are exposed in MQTT principal APIs as synthetic `synthia_node` principals:

- `principal_id=node:{node_id}`
- `status=active` when registry trust is `trusted`
- `status=revoked` when registry trust is `revoked`/`rejected`
- otherwise `status=pending`

Node lifecycle actions:

- revoke/untrust: `POST /api/system/nodes/registrations/{node_id}/revoke` (alias `/untrust`)
- remove node: `DELETE /api/system/nodes/registrations/{node_id}`
- explicit trust-state read: `GET /api/system/nodes/trust-status/{node_id}`

Revoke/remove behavior:

- both actions revoke node trust for normal trusted-node APIs
- both actions deprovision the node MQTT principal
- remove additionally deletes the registry record
- Core retains a revoked trust-status record so the node can read a formal removal/revocation message through `GET /api/system/nodes/trust-status/{node_id}`

Formal trust-loss signaling:

- nodes should not need to infer deliberate removal only from auth failures
- `GET /api/system/nodes/trust-status/{node_id}` remains readable with the last issued trust token after revoke/remove
- `support_state=revoked|removed` is the explicit Core-side signal that the node is no longer trusted/supported

## Compatibility

Legacy onboarding alias routes remain available:

- `/api/system/ai-nodes/onboarding/sessions*`

Legacy alias responses include deprecation headers and migration warning.

## See Also

- [Node Onboarding API Contract](./node-onboarding-api-contract.md)
- [Node Trust Activation Payload Contract](./node-trust-activation-payload-contract.md)
- [Node Trust Status Contract](./node-trust-status-contract.md)
- [Node Onboarding Migration Guide](./node-onboarding-migration-guide.md)
- [MQTT Platform](../mqtt/mqtt-platform.md)

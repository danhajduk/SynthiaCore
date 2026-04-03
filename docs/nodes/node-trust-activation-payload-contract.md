# Node Trust Activation Payload Contract

Status: Implemented (baseline), Partial (profile extensions)
Last updated: 2026-03-19

## Purpose

Defines the canonical trust activation payload returned when a node onboarding session is approved and finalized.

Terminology note:

- approval is the operator decision step
- trust activation is the finalize payload returned after approved finalization
- capability activation is a later post-trust phase and is not part of the trust activation payload

## Activation Payload Fields

Returned under `activation`:

- `node_id`
- `node_type`
- `paired_core_id`
- `node_trust_token`
- `initial_baseline_policy`
- `baseline_policy_version`
- `activation_profile`
- `operational_mqtt_identity`
- `operational_mqtt_token`
- `operational_mqtt_host` (non-loopback reachable Core host/IP for node connectivity)
- `operational_mqtt_port`
- `issued_at`
- `source_session_id`
- `trust_status` (`trusted` on activation issue)

## Security Properties

- Issued only for `approved` sessions.
- Session-bound and node-nonce validated.
- One-time consumption enforced by finalize flow.
- Replay attempts return `consumed`.
- No partial trust material is returned for `pending`, `rejected`, `expired`, `cancelled`, or invalid finalize outcomes.

## Extensibility

- `node_type` is explicit in payload.
- `activation_profile` provides node-type-aware extension surface.
- Baseline payload fields remain common across node classes.

## Operational MQTT Host Resolution

`activation.operational_mqtt_host` is resolved as a non-loopback host using this precedence:
1. `SYNTHIA_NODE_OPERATIONAL_MQTT_HOST` (when non-loopback)
2. `SYNTHIA_BOOTSTRAP_ADVERTISE_HOST` (when non-loopback)
3. `SYNTHIA_MQTT_HOST` (when non-loopback)
4. runtime detected advertise host

Loopback values (for example `127.0.0.1`, `localhost`, `0.0.0.0`, `::1`) are rejected for node-facing payloads.

## Registration Lifecycle Coupling

After successful finalize+consume:
- linked node registration trust status is promoted to `trusted`.
- trust activation records now also persist canonical trust-state metadata used by the trust-status contract.
- Core provisions an MQTT principal for the node with:
  - publish scope: `hexe/nodes/<node_id>/#`
  - subscribe scopes:
    - `hexe/bootstrap/core`
    - `hexe/nodes/<node_id>/#`

The node-owned namespace is intentionally restricted to:

```text
hexe/nodes/<node_id>/
|- status            # current health snapshot (retained)
|- lifecycle         # state transitions (starting, ready, degraded)
|- telemetry         # metrics / heartbeat (non-retained)
|- events            # notable events/errors
|- notify/request    # node -> Core notification proxy request
|- notify/result     # Core -> node notification proxy result
```

## Post-Activation Trust Loss

After activation, later trust changes are not communicated by replaying the activation payload.

Core instead exposes:

- `GET /api/system/nodes/trust-status/{node_id}`

That route is the canonical explicit signal for:

- active trust
- trust revoked by Core
- node removed by Core

## Validation Constraints

Status: Implemented (baseline), Partial (profile extensions)

- required baseline fields are expected to be present for successful activation responses
- `operational_mqtt_port` must be a valid TCP port
- baseline field names remain canonical across node classes
- node-type-specific extensions belong under `activation_profile`, not by renaming baseline keys

## AI-Node Profile Compatibility

AI-node consumers can continue using existing baseline fields while migrating to global node contract terminology.

## See Also

- [Node Onboarding And Trust Terminology](./onboarding-trust-terminology.md)
- [Node Onboarding API Contract](./node-onboarding-api-contract.md)
- [Node Trust Status Contract](./node-trust-status-contract.md)
- [Node Onboarding And Registration Architecture](./node-onboarding-registration-architecture.md)
- [Node Onboarding Migration Guide](./node-onboarding-migration-guide.md)
- [Node Notification MQTT Contract](./node-notification-mqtt-contract.md)

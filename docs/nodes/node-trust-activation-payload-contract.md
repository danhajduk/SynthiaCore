# Node Trust Activation Payload Contract

Status: Implemented (baseline), Partial (profile extensions)
Last updated: 2026-03-11

## Purpose

Defines the canonical trust activation payload returned when a node onboarding session is approved and finalized.

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

## Security Properties

- Issued only for `approved` sessions.
- Session-bound and node-nonce validated.
- One-time consumption enforced by finalize flow.
- Replay attempts return `consumed`.

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

## AI-Node Profile Compatibility

AI-node consumers can continue using existing baseline fields while migrating to global node contract terminology.

## See Also

- [Node Onboarding API Contract](./node-onboarding-api-contract.md)
- [Node Onboarding And Registration Architecture](./node-onboarding-registration-architecture.md)
- [Node Onboarding Migration Guide](./node-onboarding-migration-guide.md)

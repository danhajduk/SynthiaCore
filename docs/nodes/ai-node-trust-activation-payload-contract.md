# AI Node Trust Activation Payload Contract

Status: Partial
Implementation status: Profile compatibility reference; canonical trust activation contract moved to global node model
Last updated: 2026-03-11

## Purpose

This document defines the AI-node profile compatibility view of trust activation payloads.

Canonical global contract:
- [Node Trust Activation Payload Contract](./node-trust-activation-payload-contract.md)

## Canonical Response Shape

Status: Planned

```json
{
  "ok": true,
  "activation": {
    "node_id": "node-abc123",
    "paired_core_id": "synthia-core",
    "node_trust_token": "<opaque_token>",
    "initial_baseline_policy": {
      "version": "1",
      "rules": []
    },
    "baseline_policy_version": "1",
    "operational_mqtt_identity": "node:node-abc123",
    "operational_mqtt_token": "<opaque_token>",
    "operational_mqtt_host": "10.0.0.55",
    "operational_mqtt_port": 1883
  }
}
```

## Required Fields

Status: Planned

- `node_id` (string)
- `paired_core_id` (string)
- `node_trust_token` (string)
- `initial_baseline_policy` (object)
- `baseline_policy_version` (string)
- `operational_mqtt_identity` (string)
- `operational_mqtt_token` (string)
- `operational_mqtt_host` (string)
- `operational_mqtt_port` (integer)

## Optional / Future Fields

Status: Planned

- Additional transport endpoints (if future protocols are enabled)
- Policy metadata extensions that are backward-compatible

No alternate names are allowed for required canonical fields.

## Naming Constraints

Status: Planned

The following alternate names must not replace canonical fields:
- `node_token` (use `node_trust_token`)
- `mqtt_credentials` (use `operational_mqtt_identity` + `operational_mqtt_token`)
- `core_id` in place of `paired_core_id`

## Validation Rules

Status: Planned

- Payload is returned only for approved onboarding sessions.
- Payload must not be returned for `pending`, `rejected`, `expired`, `cancelled`, or already-consumed non-repeatable flows.
- Field presence is strict for required keys.
- `operational_mqtt_port` must be a valid TCP port number.

## Error Envelope Guidance

Status: Planned

When activation cannot be returned:
- return deterministic error code and message
- do not return partial trust material

## See Also

- [AI Node Onboarding API Contract](./ai-node-onboarding-api-contract.md)
- [AI Node Onboarding Approval Architecture](./ai-node-onboarding-approval-architecture.md)
- [AI Node Onboarding Approval URL Contract](./ai-node-onboarding-approval-url-contract.md)

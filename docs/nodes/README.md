# Nodes Docs

This is the canonical entrypoint for Nodes documentation in the `Core -> Supervisor -> Nodes` structure.

## Status

Status: Implemented

Current node code boundaries:

- `backend/app/system/onboarding/`
- `backend/app/nodes/`

## Current Responsibilities

- onboarding sessions and approval flow
- registration and trust activation
- capability declaration and profile acceptance
- governance issuance and refresh
- telemetry ingestion and operational status projection
- external functionality and execution surfaces in the migration model
- migration-foundation route exposure through:
  - `GET /api/nodes`
  - `GET /api/nodes/{node_id}`

The new top-level node routes reuse the existing canonical registration payload shape.

## Boundary Rules

- Nodes are the canonical model for new external functionality and trusted host-separated execution.
- Embedded addons remain inside Core and should not be used to describe external platform boundaries.
- Core remains the MQTT authority, and node connectivity material continues to be issued from Core-owned flows.

## Capability Taxonomy

- Nodes now expose a canonical capability taxonomy with stable categories for task families, provider access, and provider models.
- Capability activation semantics are standardized through taxonomy stages from `not_declared` through `operational`.

## Included Docs

- [capability-taxonomy.md](./capability-taxonomy.md)
- [onboarding-trust-terminology.md](./onboarding-trust-terminology.md)
- [registry-domain.md](./registry-domain.md)
- [node-onboarding-registration-architecture.md](./node-onboarding-registration-architecture.md)
- [node-onboarding-api-contract.md](./node-onboarding-api-contract.md)
- [node-phase2-lifecycle-contract.md](./node-phase2-lifecycle-contract.md)
- [node-lifecycle.md](./node-lifecycle.md)

## See Also

- [../architecture.md](../architecture.md)
- [../fastapi/api-reference.md](../fastapi/api-reference.md)
- [../mqtt/mqtt-platform.md](../mqtt/mqtt-platform.md)
- [../temp-ai-node/README.md](../temp-ai-node/README.md)

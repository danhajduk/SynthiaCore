# Hexe Nodes Docs

This is the canonical entrypoint for Hexe Nodes documentation in the `Core -> Supervisor -> Nodes` structure.

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

## Canonical Node Lifecycle

Canonical node lifecycle states used across the node docs:

- `unconfigured`
- `bootstrap_connecting`
- `bootstrap_connected`
- `core_discovered`
- `registration_pending`
- `pending_approval`
- `trusted`
- `capability_setup_pending`
- `capability_declaration_in_progress`
- `capability_declaration_accepted`
- `capability_declaration_failed_retry_pending`
- `operational`
- `degraded`

This lifecycle model is documented in [node-lifecycle.md](./node-lifecycle.md). Current Core APIs still expose some adjacent status through separate readiness and synchronization projections such as `capability_status`, `governance_status`, and `operational_ready`.

## Boundary Rules

- Nodes are the canonical model for new external functionality and trusted host-separated execution.
- Embedded addons remain inside Core and should not be used to describe external platform boundaries.
- Core remains the MQTT authority, and node connectivity material continues to be issued from Core-owned flows.

Compatibility note: Hexe Nodes is the current display label, and active MQTT namespace examples now use `hexe/...`. Stable technical contracts such as API paths and some internal identifiers still retain legacy forms where compatibility matters.

## Capability Taxonomy

- Nodes now expose a canonical capability taxonomy with stable categories for task families, provider access, and provider models.
- Capability activation semantics are standardized through taxonomy stages from `not_declared` through `operational`.

## Included Docs

- [capability-taxonomy.md](./capability-taxonomy.md)
- [onboarding-trust-terminology.md](./onboarding-trust-terminology.md)
- [registry-domain.md](./registry-domain.md)
- [node-onboarding-registration-architecture.md](./node-onboarding-registration-architecture.md)
- [node-onboarding-api-contract.md](./node-onboarding-api-contract.md)
- [scheduled-work-execution-contract.md](./scheduled-work-execution-contract.md)
- [node-phase2-lifecycle-contract.md](./node-phase2-lifecycle-contract.md)
- [node-lifecycle.md](./node-lifecycle.md)

## See Also

- [../architecture.md](../architecture.md)
- [../fastapi/api-reference.md](../fastapi/api-reference.md)
- [../mqtt/mqtt-platform.md](../mqtt/mqtt-platform.md)
- [../temp-ai-node/README.md](../temp-ai-node/README.md)

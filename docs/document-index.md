# Synthia Documentation Index

This is the recommended first-read document for both operators and developers.

Synthia is a Core + Addons platform with an embedded MQTT control/data plane, scheduler/worker runtime, and admin UI.

## Canonical Documentation (Start Here)

- [Repository Docs Index](./index.md)
- [Overview](./overview.md)
- [Platform Architecture](./platform-architecture.md)
- [FastAPI Docs](./fastapi/README.md)
- [Core Platform](./fastapi/core-platform.md)
- [Addon Platform](./addon-embedded/addon-platform.md)
- [Standalone Addons](./addon-standalone/README.md)
- [MQTT Docs](./mqtt/README.md)
- [MQTT Platform](./mqtt/mqtt-platform.md)
- [Notifications Bus](./mqtt/notifications.md)
- [Runtime and Supervision](./supervisor/runtime-and-supervision.md)
- [Auth and Identity](./fastapi/auth-and-identity.md)
- [Data and State](./fastapi/data-and-state.md)
- [API Reference](./fastapi/api-reference.md)
- [Frontend and UI](./frontend/frontend-and-ui.md)
- [Scheduler Docs](./scheduler/README.md)
- [Worker Docs](./workers/README.md)
- [Node Docs](./nodes/README.md)
- [Operators Guide](./operators-guide.md)
- [Development Guide](./development-guide.md)

## Active Reference Docs

- [Roadmap](./ROADMAP.md)
- [Documentation Migration Map](./documentation-migration-map.md)
- [AI Node Docs Mapping](./nodes/ai-node-docs-mapping.md)
- [Node Onboarding And Registration Architecture](./nodes/node-onboarding-registration-architecture.md)
- [Node Onboarding API Contract](./nodes/node-onboarding-api-contract.md)
- [Node Onboarding Phase 1 Contract](./nodes/node-onboarding-phase1-contract.md)
- [Node Trust Activation Payload Contract](./nodes/node-trust-activation-payload-contract.md)
- [Node Onboarding Migration Guide](./nodes/node-onboarding-migration-guide.md)
- [Node Capability Activation Architecture (Phase 2)](./nodes/node-capability-activation-architecture.md)
- [Node Phase 2 Lifecycle Contract](./nodes/node-phase2-lifecycle-contract.md)
- [AI Node Onboarding Approval Architecture](./nodes/ai-node-onboarding-approval-architecture.md)
- [AI Node Onboarding API Contract](./nodes/ai-node-onboarding-api-contract.md) (profile compatibility view)
- [AI Node Onboarding Approval URL Contract](./nodes/ai-node-onboarding-approval-url-contract.md)
- [AI Node Trust Activation Payload Contract](./nodes/ai-node-trust-activation-payload-contract.md) (profile compatibility view)
- [Distributed Addons Reference](./distributed_addons/README.md)
- [Addon Store Incident Runbook](./addon-store/incident-runbook.md)
- JSON schemas:
  - [`desired.schema.json`](./desired.schema.json)
  - [`runtime.schema.json`](./runtime.schema.json)
  - [`addon-manifest.schema.json`](./addon-manifest.schema.json)

## Runbooks

- [Operators Guide](./operators-guide.md) (canonical runbook)
- [Addon Store Incident Runbook](./addon-store/incident-runbook.md)

## AI Node Architecture Track

Status: Planned

- Canonical source: `/home/dan/Projects/SynthiaAiNode/docs` (node-first ownership)
- Mapping and sync policy: [AI Node Docs Mapping](./nodes/ai-node-docs-mapping.md)
- Global onboarding authority: [Node Onboarding And Registration Architecture](./nodes/node-onboarding-registration-architecture.md)
- Core-side onboarding authority: [AI Node Onboarding Approval Architecture](./nodes/ai-node-onboarding-approval-architecture.md)
- Core-side onboarding API contract: [Node Onboarding API Contract](./nodes/node-onboarding-api-contract.md)
- Core-side approval URL/session binding contract: [AI Node Onboarding Approval URL Contract](./nodes/ai-node-onboarding-approval-url-contract.md)
- Core-side trust activation payload contract: [Node Trust Activation Payload Contract](./nodes/node-trust-activation-payload-contract.md)
- Migration/sunset guidance: [Node Onboarding Migration Guide](./nodes/node-onboarding-migration-guide.md)
- AI Node canonical docs:
  - `/home/dan/Projects/SynthiaAiNode/docs/phase1-overview.md`
  - `/home/dan/Projects/SynthiaAiNode/docs/ai-node-architecture.md`
  - `/home/dan/Projects/SynthiaAiNode/docs/node-capability-declaration.md`

## Archived and Legacy

- [Archive Directory](./archive/)
- [Documentation Migration Summary](./documentation-migration-summary.md)

## Documentation Maintenance Rules

- Update canonical docs first; avoid creating overlapping top-level docs.
- Archive old docs only after transferring useful content.
- Mark behavior explicitly as `Implemented`, `Partial`, `Planned`, or `Archived Legacy`.
- Treat this index as the docs front door and keep links current.

## See Also

- [Overview](./overview.md)
- [Development Guide](./development-guide.md)
- [Documentation Migration Map](./documentation-migration-map.md)

# Synthia Documentation Index

This is the recommended first-read document for both operators and developers.

Synthia is a Core + Addons platform with an embedded MQTT control/data plane, scheduler/worker runtime, and admin UI.

## Canonical Documentation (Start Here)

- [Overview](./overview.md)
- [Platform Architecture](./platform-architecture.md)
- [Core Platform](./core-platform.md)
- [Addon Platform](./addon-platform.md)
- [MQTT Platform](./mqtt-platform.md)
- [Runtime and Supervision](./runtime-and-supervision.md)
- [Auth and Identity](./auth-and-identity.md)
- [Data and State](./data-and-state.md)
- [API Reference](./api-reference.md)
- [Frontend and UI](./frontend-and-ui.md)
- [Operators Guide](./operators-guide.md)
- [Development Guide](./development-guide.md)

## Active Reference Docs

- [Roadmap](./ROADMAP.md)
- [Documentation Migration Map](./documentation-migration-map.md)
- [AI Node Docs Mapping](./ai-node-docs-mapping.md)
- [Node Onboarding And Registration Architecture](./node-onboarding-registration-architecture.md)
- [Node Onboarding API Contract](./node-onboarding-api-contract.md)
- [Node Onboarding Phase 1 Contract](./node-onboarding-phase1-contract.md)
- [Node Trust Activation Payload Contract](./node-trust-activation-payload-contract.md)
- [Node Onboarding Migration Guide](./node-onboarding-migration-guide.md)
- [Node Capability Activation Architecture (Phase 2)](./node-capability-activation-architecture.md)
- [AI Node Onboarding Approval Architecture](./ai-node-onboarding-approval-architecture.md)
- [AI Node Onboarding API Contract](./ai-node-onboarding-api-contract.md) (profile compatibility view)
- [AI Node Onboarding Approval URL Contract](./ai-node-onboarding-approval-url-contract.md)
- [AI Node Trust Activation Payload Contract](./ai-node-trust-activation-payload-contract.md) (profile compatibility view)
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
- Mapping and sync policy: [AI Node Docs Mapping](./ai-node-docs-mapping.md)
- Global onboarding authority: [Node Onboarding And Registration Architecture](./node-onboarding-registration-architecture.md)
- Core-side onboarding authority: [AI Node Onboarding Approval Architecture](./ai-node-onboarding-approval-architecture.md)
- Core-side onboarding API contract: [Node Onboarding API Contract](./node-onboarding-api-contract.md)
- Core-side approval URL/session binding contract: [AI Node Onboarding Approval URL Contract](./ai-node-onboarding-approval-url-contract.md)
- Core-side trust activation payload contract: [Node Trust Activation Payload Contract](./node-trust-activation-payload-contract.md)
- Migration/sunset guidance: [Node Onboarding Migration Guide](./node-onboarding-migration-guide.md)
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

# Node Onboarding And Registration Architecture

Status: Partial
Implementation status: Partial (global registration domain model/store exists; onboarding accepts configured node types via `SYNTHIA_NODE_ONBOARDING_SUPPORTED_TYPES`)
Last updated: 2026-03-11

## Purpose

This document defines the canonical global node onboarding and registration architecture for Synthia Core.

It generalizes onboarding from AI-node-only assumptions to a node-type-aware model that supports future node classes.

## Scope

Status: Partial

- Global onboarding session lifecycle for all node types.
- Global node registration model and trust lifecycle.
- Compatibility path for existing AI-node onboarding clients.

## Core Principles

Status: Implemented (baseline)

- Core remains trust authority.
- Onboarding is operator-mediated and session-based.
- Session and registration state are server-authoritative and auditable.
- Node-specific behavior is profile-driven by `node_type`, not hard-coded AI-only semantics.
- Compatibility aliases may exist during migration, but canonical contracts remain global.

## Global Lifecycle

Status: Implemented (baseline)

1. Node starts onboarding session (`node_type` + identity metadata + nonce binding).
2. Core creates pending onboarding session with expiry.
3. Core returns approval URL for operator review.
4. Operator authenticates in Core and approves/rejects.
5. Node finalizes/polls using session binding.
6. Core returns trust activation payload for approved sessions.
7. Node registration record transitions to trusted/active lifecycle.

## Global Node Types

Status: Partial

- `ai-node` is the initial implemented profile.
- Future node types can reuse the same onboarding and registration contract with profile-specific payload extensions.

Current expectation:
- Unknown `node_type` is rejected unless explicitly supported.

## Registration Model Boundary

Status: Partial

Global registration record should include:
- `node_id`
- `node_type`
- `node_name`
- `software_version`
- trust status and lifecycle state
- provenance fields (onboarding session, approval actor/timestamps)

Implemented baseline:
- persisted global registration store (`data/node_registrations.json`)
- onboarding approval binds approved sessions to registration records
- schema/version marker and compatibility aliases for legacy AI-node field names

## Security And Trust Boundary

Status: Partial

Implemented baseline:
- session binding via `node_nonce`
- approval URL state token checks
- one-time trust consumption
- expiry and terminal state protections
- onboarding audit events

Planned extension:
- profile-specific policy constraints by `node_type`
- stronger cross-node binding guarantees for advanced node classes

## AI-Node Compatibility

Status: Implemented (with migration path)

- Existing AI-node onboarding APIs/flows remain supported during migration.
- AI-node-specific docs become profile references under this global architecture.
- Deprecation plan should remove AI-only naming once global contracts are fully adopted.

## Canonical Surfaces

Status: Implemented (baseline), Partial (future type-specific extensions)

- Bootstrap onboarding advertisement
- Onboarding session creation API
- Approval UI and decision APIs
- Finalization/polling API
- Trust activation payload
- Global node registration APIs

Current contract references:
- [Node Onboarding API Contract](./node-onboarding-api-contract.md)
- [Node Trust Activation Payload Contract](./node-trust-activation-payload-contract.md)
- [Node Onboarding Migration Guide](./node-onboarding-migration-guide.md)

## See Also

- [AI Node Onboarding Approval Architecture](./ai-node-onboarding-approval-architecture.md)
- [Node Onboarding API Contract](./node-onboarding-api-contract.md)
- [Node Trust Activation Payload Contract](./node-trust-activation-payload-contract.md)
- [API Reference](./api-reference.md)
- [Operators Guide](./operators-guide.md)

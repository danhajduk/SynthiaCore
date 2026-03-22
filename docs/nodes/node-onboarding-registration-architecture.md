# Node Onboarding And Registration Architecture

Status: Partial
Implementation status: Partial (global registration domain model/store exists; onboarding accepts configured node types via `SYNTHIA_NODE_ONBOARDING_SUPPORTED_TYPES`)
Last updated: 2026-03-20 10:16

## Purpose

This document defines the canonical global node onboarding and registration architecture for Hexe Core.

Canonical terminology for onboarding, registration, trust activation, and capability activation is defined in [Node Onboarding And Trust Terminology](./onboarding-trust-terminology.md).

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

Canonical end-to-end node lifecycle:

1. `Node Identity` -> `unconfigured`
Node presents `node_type`, node metadata, optional UI location metadata, and nonce binding.

2. `Core Connection` -> `bootstrap_connecting`
Node reaches Core's bootstrap MQTT listener.

3. `Bootstrap Discovery` -> `bootstrap_connected` then `core_discovered`
Node reads retained bootstrap metadata from `hexe/bootstrap/core`.

4. `Registration` -> `registration_pending`
Node starts the onboarding session and Core persists the pending session.

5. `Approval` -> `pending_approval`
Operator authenticates in Core and approves or rejects the session.

6. `Trust Activation` -> `trusted`
Node finalizes with its session binding and receives trust material plus operational MQTT credentials.

7. `Provider Setup` -> `capability_setup_pending`
Node performs local provider selection and readiness checks.

8. `Capability Declaration` -> `capability_declaration_in_progress`
Node submits its capability manifest to Core.

9. `Governance Sync` -> `capability_declaration_accepted`
Node fetches or refreshes the effective governance bundle.

10. `Ready` -> `operational`
Core projects `operational_ready=true`.

The onboarding model is operator-mediated rather than OAuth-style:

- node starts an onboarding session
- Core returns an approval URL
- operator reviews and decides in Core
- node polls/finalizes against the stored session
- Core issues trust material only after approval

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
- optional operator-facing location metadata such as `requested_hostname` and `requested_ui_endpoint`
- provenance fields (onboarding session, approval actor/timestamps)

Implemented baseline:
- persisted global registration store (`data/node_registrations.json`)
- onboarding approval binds approved sessions to registration records
- onboarding persists optional `requested_hostname` and `requested_ui_endpoint` metadata for later operator UI linking
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

## Approval URL And Headless Flow

Status: Implemented (baseline)

Approval URLs are safe to display to operators in headless-node workflows.

Canonical format:
- `<core_base>/onboarding/nodes/approve?sid=<session_id>&state=<state_token>`

Server-authoritative rules:
- `sid` and `state` are lookup and tamper-detection hints, not authority state
- session metadata, decision state, expiry, and linked node identity remain server-side only
- trust tokens and MQTT operational credentials are never embedded in the URL

Headless compatibility:
- node runtime does not need an embedded browser
- operator can complete approval and login entirely in the Core UI
- node only needs to surface the approval URL and continue polling/finalizing

## Canonical Approval Flow

Status: Implemented (baseline)

1. Node calls the onboarding start API with identity metadata, optional UI endpoint metadata, and `node_nonce`.
2. Core validates request data, supported `node_type`, and protocol compatibility.
3. Core creates a persisted pending session with expiry and returns the approval URL.
4. Operator opens the approval URL and authenticates in Core if needed.
5. Operator approves or rejects the pending session.
6. Node polls/finalizes using the session id plus the same `node_nonce`.
7. Core returns deterministic pending, rejected, expired, consumed, invalid, or approved outcomes.

Decision semantics:
- pending sessions may be viewed multiple times
- only one terminal approve or reject action is allowed
- expired sessions become terminal and cannot be approved
- approved finalization is one-time consumable

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

- [AI Node Onboarding Approval Architecture](../temp-ai-node/ai-node-onboarding-approval-architecture.md)
- [Node Onboarding API Contract](./node-onboarding-api-contract.md)
- [Node Trust Activation Payload Contract](./node-trust-activation-payload-contract.md)
- [API Reference](../fastapi/api-reference.md)
- [Operators Guide](../operators-guide.md)

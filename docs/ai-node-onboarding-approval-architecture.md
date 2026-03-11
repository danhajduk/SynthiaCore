# AI Node Onboarding Approval Architecture

Status: Planned
Implementation status: Not developed
Last updated: 2026-03-11

## Purpose

This document defines the canonical Core-side architecture for AI Node onboarding approval.
It is the implementation authority for Tasks 431-440.

The onboarding model is operator-mediated:

1. AI Node requests onboarding session.
2. Core creates a pending onboarding session.
3. Core returns an operator approval URL.
4. Operator logs into Core UI if needed.
5. Operator approves or rejects node onboarding.
6. AI Node polls/finalizes onboarding.
7. Core issues trust activation payload only after approval.

This is not a generic OAuth redirect flow.

## Architecture Principles

Status: Planned

- Core remains trust authority.
- Onboarding is session-based and auditable.
- Trust material is issued only from approved persisted sessions.
- Flow must work for headless AI Nodes by displaying an operator URL.
- Server-side session state is source of truth.

## Participating Surfaces

Status: Planned

- Bootstrap payload surface:
  - Advertises onboarding capabilities and API entry points.
- Onboarding session API surface:
  - Node starts onboarding and receives a pending session + approval URL.
- Approval UI surface:
  - Operator-facing Core page that requires authenticated Core session.
- Finalization API surface:
  - Node polls/consumes decision and, when approved, receives trust activation payload.
- Trust activation payload surface:
  - Canonical response contract for approved node pairing and operational identity bootstrap.

## Canonical Flow

Status: Planned

### 1) Node Starts Onboarding

- Node calls Core onboarding start API with requested identity metadata.
- Core validates request and creates onboarding session with expiry.
- Core returns `session_id`, `pending_approval` status, and approval URL.

### 2) Operator Approval URL Handling

- Approval URL resolves to Core onboarding approval page.
- If operator is not authenticated, Core login is required first.
- After login, operator returns to the same onboarding approval page.

### 3) Operator Decision

- Core shows pending node request details and expiry.
- Operator explicitly approves or rejects.
- Core persists durable decision and actor identity.

### 4) Node Finalization

- Node polls/finalizes using onboarding session binding.
- If pending: node remains waiting.
- If rejected/expired: node receives deterministic failure state.
- If approved: node receives trust activation payload.

### 5) Trust Establishment

- Node persists trust activation payload locally as sensitive state.
- Node transitions from onboarding to trusted lifecycle path.

## Headless Compatibility

Status: Planned

- Node does not require embedded browser capability.
- Node only needs to surface approval URL to operator.
- Approval and login occur in Core UI independently from node runtime.

## Security Boundaries

Status: Planned

- Approval URL references a persisted onboarding session.
- Session expiry gates decisions and finalization.
- Approval/rejection must be one authoritative decision per session.
- Trust payload issuance is blocked for non-approved sessions.
- Audit trail captures request, decision actor, and finalization events.

## Out of Scope

Status: Planned

- Generic third-party OAuth provider integration.
- Browser redirect-back requirement from Core to AI Node.
- Capability declaration and provider enablement (handled in later phases).

## See Also

- [AI Node Docs Mapping](./ai-node-docs-mapping.md)
- [Auth and Identity](./auth-and-identity.md)
- [API Reference](./api-reference.md)
- [Platform Architecture](./platform-architecture.md)

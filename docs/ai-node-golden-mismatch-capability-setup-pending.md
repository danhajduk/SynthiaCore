# AI Node Golden Mismatch Report - `capability_setup_pending` Required Data

Status: Resolved (local golden docs updated)
Generated: 2026-03-11
Scope:
- Golden docs: `docs/ai-node-architecture.md`, `docs/phase1-overview.md`
- Runtime code references: `src/ai_node/runtime/node_control_api.py`, `src/ai_node/runtime/capability_declaration_runner.py`, `src/ai_node/main.py`

## Summary

- Total findings: 2
- Highest-risk drift (resolved): golden docs previously defined lifecycle transition without required setup-state payload/readiness contract for `capability_setup_pending`.
- Resolution action: added explicit golden contract section for `capability_setup_pending` prerequisites and setup polling API shape.

## Findings

### Finding 1: Missing golden contract for required `capability_setup_pending` data

Type:
- Missing documentation (resolved)

Affected files:
- `docs/ai-node-architecture.md`
- `docs/phase1-overview.md`

What code shows:
- Node status payload in runtime includes fields that drive setup behavior:
  - lifecycle status
  - `provider_selection_configured`
  - `trusted_runtime_context`
  - `capability_declaration` object
- Capability declaration execution depends on trusted state + provider selection + runtime context.

What golden docs say:
- Golden docs describe the lifecycle transition `trusted -> capability_setup_pending -> operational`.
- Golden docs do not define required data contract for this state.

Why this is a mismatch:
- Lifecycle state exists in golden docs, but operators/clients are not told what data must be present to safely proceed in this state.

Resolution:
- Added `capability_setup_pending` contract section in:
  - `docs/ai-platform-roadmap.md`
- Added required setup-state readiness fields:
  - trusted identity context
  - provider selection readiness
  - capability declaration status
  - governance sync status
  - blocking/transition contract

### Finding 2: Missing golden API payload contract for setup-state polling

Type:
- Missing source-of-truth document (resolved)

Affected files:
- `docs/ai-node-architecture.md`
- `docs/phase1-overview.md`

What code shows:
- `GET /api/node/status` is currently used as lifecycle-first polling source for setup UI.
- UI behavior in setup state depends on status payload stability.

What golden docs say:
- Golden docs provide conceptual lifecycle but no canonical status payload schema for `capability_setup_pending`.

Why this is a mismatch:
- Clients can detect the state name, but not a stable contract for readiness flags or blocking conditions.

Resolution:
- Added setup-state polling contract subsection in:
  - `docs/ai-platform-roadmap.md`
- Canonical endpoint documented:
  - `GET /api/system/nodes/operational-status/{node_id}`
- Required setup payload fields documented for lifecycle/readiness polling.

## Evidence Notes

- Local golden reference now codifies setup-state contract in `docs/ai-platform-roadmap.md`.
- Canonical API field set aligns with implemented operational status contract in `docs/node-phase2-lifecycle-contract.md`.

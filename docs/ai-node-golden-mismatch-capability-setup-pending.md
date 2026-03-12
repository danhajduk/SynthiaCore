# AI Node Golden Mismatch Report - `capability_setup_pending` Required Data

Status: Open
Generated: 2026-03-11
Scope:
- Golden docs: `docs/ai-node-architecture.md`, `docs/phase1-overview.md`
- Runtime code references: `src/ai_node/runtime/node_control_api.py`, `src/ai_node/runtime/capability_declaration_runner.py`, `src/ai_node/main.py`

## Summary

- Total findings: 2
- Highest-risk drift: golden docs define lifecycle state transition but do not define required status payload/readiness contract for `capability_setup_pending`.
- Next action: add explicit golden contract section for `capability_setup_pending` prerequisites and API shape.

## Findings

### Finding 1: Missing golden contract for required `capability_setup_pending` data

Type:
- Missing documentation

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

Recommended fix:
- Add a golden section specifying required `capability_setup_pending` data:
  - trusted identity context
  - provider selection readiness
  - capability declaration readiness/status
  - blocking reasons contract

### Finding 2: Missing golden API payload contract for setup-state polling

Type:
- Missing source-of-truth document

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

Recommended fix:
- Add a golden API contract subsection for `GET /api/node/status` fields relevant to `capability_setup_pending`.

## Evidence Notes

- `docs/ai-node-architecture.md` includes lifecycle state name and transition notes, but not required setup-state data fields.
- `docs/phase1-overview.md` and split phase docs include canonical path but no required setup-state payload shape.
- Runtime/API code currently carries setup-related fields not codified in golden docs.


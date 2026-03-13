# Synthia Repository Audit Report

Generated: 2026-03-12 15:05  
Repository: SynthiaAiNode  
Audit Mode: Core Documentation Gap Audit (Tasks 125-130)

Canonical Core Documentation:
/home/dan/Projects/Synthia/docs

---

# Architecture Audit Summary

Subsystems detected:

- Node provider intelligence ingestion path (Node -> Core)
- Provider intelligence refresh/publish workflow
- Node-local provider runtime/metrics/router stack
- Node-local debug/test infrastructure

Total findings: 2

Highest-risk drift:
Core endpoint existence is documented, but no canonical provider-intelligence ingestion request/response schema contract is published for Node clients.

---

# Architecture Findings

## Finding 1

Type: Missing source-of-truth document  
Severity: High  

Affected files:

/home/dan/Projects/Synthia/docs/api-reference.md  
/home/dan/Projects/Synthia/docs/ai-node-golden-mismatch-provider-intelligence.md  
docs/New_tasks.txt  
src/ai_node/core_api/capability_client.py  

Explanation:

Task 125 requires publishing provider intelligence to Core. Core docs currently list the ingestion endpoint (`POST /api/system/nodes/providers/capabilities/report`) but do not provide a normative request/response contract document (required fields, schema versions, validation rules, error envelope, idempotency semantics).

Recommended fix:

Add a canonical Core contract doc for provider-intelligence ingestion and link it from `api-reference.md`.

---

## Finding 2

Type: Missing documentation  
Severity: Medium  

Affected files:

/home/dan/Projects/Synthia/docs/api-reference.md  
/home/dan/Projects/Synthia/docs/core-platform.md  
docs/New_tasks.txt  

Explanation:

Task 126 requires a periodic refresh/publish job. Core docs describe telemetry/routing outcomes and expose read endpoints, but do not define Node-to-Core refresh contract expectations (cadence bounds, change-detection criteria, retry/backoff requirements, and minimal publish conditions for provider intelligence).

Recommended fix:

Add contract-level refresh semantics in Core docs for provider intelligence publication lifecycle, including timing bounds and failure handling expectations for trusted nodes.

---

# Documentation Audit Summary

Files updated:

docs/reports/core-missing-docs-audit-2026-03-12.md

Archived documentation:

None

Remaining gaps:

- No canonical schema contract for provider intelligence ingestion request/response.
- No canonical refresh/publication lifecycle contract for provider intelligence updates.

Re-check update (2026-03-12):
- Canonical ingestion contract published:
  - `/home/dan/Projects/Synthia/docs/node-provider-intelligence-report-contract.md`
- Canonical refresh/publication lifecycle contract published:
  - `/home/dan/Projects/Synthia/docs/node-provider-intelligence-refresh-lifecycle-contract.md`
- `api-reference.md` now cross-links both contracts from the ingestion endpoint entry.

---

# Recommended Follow-Up Tasks

- Publish a Core source-of-truth contract doc for `POST /api/system/nodes/providers/capabilities/report`.
- Define canonical payload schema sections: `providers`, `models`, `metrics_snapshot` (required/optional fields and types).
- Define canonical response envelope: accepted/rejected/retryable states with error structure.
- Define refresh cadence and retry/backoff policy for Node provider intelligence publication.
- Cross-link the new contract from `/home/dan/Projects/Synthia/docs/api-reference.md` and relevant lifecycle docs.

---

# Audit Coverage Matrix

| Task | Ownership | Core Doc Coverage | Status |
|---|---|---|---|
| 125 Expose provider intelligence to Core | Core-owned contract | Partial (endpoint listed only) | Missing source-of-truth contract |
| 126 Provider intelligence refresh job | Mixed (Node impl + Core expectations) | Partial | Missing Core refresh semantics |
| 127 Debug endpoints for provider visibility | Node-owned | Not required | No Core docs required |
| 128 Structured logging for provider execution | Node-owned | Not required | No Core docs required |
| 129 Phase 4 unit tests | Node-owned | Not required | No Core docs required |
| 130 Mock provider for local testing | Node-owned | Not required | No Core docs required |

---

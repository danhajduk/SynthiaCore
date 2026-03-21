# AI-Node Mismatch Report: Task 125 (Provider Intelligence Upstream Payload)

Date: 2026-03-12
Task: 125 - Expose provider intelligence to Core
Repository: /home/dan/Projects/HexeAiNode
Canonical docs source: /home/dan/Projects/Hexe/docs

## Summary

Task 125 requires the AI-Node to publish provider intelligence to Core using a Core-owned ingestion contract.

Golden docs currently define endpoint existence (`POST /api/system/nodes/providers/capabilities/report`) and auth header class (`X-Node-Trust-Token`) in `api-reference.md`, but do not define a normative request/response payload schema for this endpoint.

Per task directive Rule 2 (missing Core-owned specification), implementation must stop until Core docs provide the contract.

## What Is Missing

1. Request payload contract for provider intelligence report:
- canonical top-level key name(s)
- required vs optional fields
- field types and value constraints
- schema/versioning behavior

2. Provider/model metric contract:
- required metric names
- aggregation windows
- precision/units for latency and pricing
- failure taxonomy expectations

3. Response contract:
- accepted/rejected/retryable status envelope
- idempotency/conflict semantics
- partial-ingestion semantics if payload is partially valid

4. Size/privacy/retention constraints:
- payload size limits
- redaction expectations
- allowed historical vs snapshot data

## Where Discovered

- `/home/dan/Projects/Hexe/docs/api-reference.md`
- `/home/dan/Projects/Hexe/docs/ai-node-golden-mismatch-provider-intelligence.md`

## Implementation Dependency

Task 125 depends on a stable Core-owned contract to map AI-Node runtime intelligence payloads to Core ingestion semantics without inventing field names/structures.

## Why Core Must Define This

The endpoint is Core-owned and authoritative. Any payload shape or acceptance behavior defined in AI-Node would create silent contract drift and may break ingestion, compatibility, and lifecycle behavior across nodes.

## Required Next Step

Add a normative Core contract document for `POST /api/system/nodes/providers/capabilities/report`, including request/response schemas and compatibility rules.

After this is published, AI-Node Task 125 implementation can resume.

## Re-check Update (2026-03-12)

Re-validated canonical docs after new Core updates. `api-reference.md` now lists related endpoints (`POST /api/system/nodes/providers/capabilities/report`, `GET /api/system/nodes/providers/intelligence`), but no normative request/response schema contract document was found under `/home/dan/Projects/Hexe/docs` for provider intelligence ingestion payload structure.

Task 125 remains blocked pending canonical Core contract publication.

## Re-check Update (2026-03-12, Resolution)

Canonical contract is now published:
- `/home/dan/Projects/Hexe/docs/node-provider-intelligence-report-contract.md`

This document defines the Core-owned request/response contract, validation/error behavior, compatibility modes, and current implementation boundaries for provider intelligence ingestion.

Task 125 documentation blocker is resolved from Core documentation side.

# AI Node Golden Mismatch: Provider Intelligence (Tasks 091-095)

Date: 2026-03-11
Scope: Synthia AI Node provider discovery, latency metrics, capability report, Core submission, and periodic refresh.

## Summary

Tasks 091-095 in `/home/dan/Projects/SynthiaAiNode/docs/New_tasks.txt` require provider-intelligence behaviors that are not currently specified in golden docs with a stable backend contract.

Per task directive, implementation is paused until golden contract details are defined.

## Missing Golden Contract Data

1. Provider discovery contract
- Which provider APIs are authoritative for model discovery.
- Required auth model per provider for discovery-only calls.
- Expected fallback behavior when provider APIs are unavailable.

2. Canonical model schema
- Required fields for each discovered model (exact names/types).
- Context window semantics (`input`, `output`, or total).
- Modality encoding (`text`, `image`, `audio`, multimodal format).
- Pricing representation (currency, unit basis, prompt/completion split, unknown handling).
- Versioning rules for schema evolution.

3. Latency measurement contract
- Probe type allowed per provider (non-billable vs minimal billable request).
- Measurement window and sample count.
- Required stats (`avg`, `p95`, `success_rate`) computation rules.
- Failure classification and retry policy.

4. Provider capability report contract
- Full report payload schema expected by Core.
- Which fields are mandatory vs optional.
- Payload size constraints and redaction/privacy rules.
- Local persistence format and retention rules.

5. Core submission contract
- Exact endpoint(s) for provider intelligence submission.
- HTTP method, auth headers, and expected response format.
- Idempotency behavior and conflict/version handling.
- Whether submission is additive to current capability declaration or separate.

6. Refresh and change-notification contract
- Required refresh interval bounds and defaults.
- Change-detection criteria (what counts as material change).
- Core notification endpoint/event model when capabilities change.
- Backoff behavior during provider/API outages.

## Impacted Tasks

- Task 091: blocked by missing discovery + canonical schema contract.
- Task 092: blocked by missing latency measurement policy contract.
- Task 093: blocked by missing provider report payload contract.
- Task 094: blocked by missing Core submission endpoint/response contract.
- Task 095: blocked by missing refresh cadence + change notification contract.

## Required Golden Updates

Please add a normative provider-intelligence contract doc that defines:
- canonical schemas
- endpoint contracts
- timing/refresh rules
- compatibility/versioning rules

After that update lands, implementation can resume safely.

# SAS v1.1 Implementation Plan (Core Store + Manifest)

Reference: `docs/Policies/Synthia_Addon_Standard.md`.

## Scope
- Store catalog management (index + publishers parsing and release selection).
- Addon manifest management (schema normalization + validation and profile/permission handling).

## Current State vs SAS v1.1

| Area | SAS v1.1 Expectation | Current Core Behavior | Gap |
|---|---|---|---|
| Manifest permission vocabulary | Canonical permissions with legacy alias normalization | Core validates canonical permission enum only | Missing alias normalization for legacy addon manifests |
| Catalog release layout | `channels` object with channel arrays (`stable`, optional `beta/nightly`) | Core resolves from legacy flat `releases[]` | Missing channels support |
| Signature metadata shape | Signature object (`signature.type`, `signature.value`) supported | Core primarily reads `release_sig` + `signature_type` | Missing object-form parsing |
| Package profile consistency | Catalog release + manifest profile should be coherent and diagnosable | Profile drives install checks; mismatch diagnostics exist but can be clearer | Needs explicit cross-check path |
| Regression coverage | SAS v1.1 parsing/selection behavior covered by tests | Existing tests cover current paths only | Needs targeted SAS coverage |

## Task Mapping
- Task 50: Manifest permission alias normalization.
- Task 51: Catalog channels support in release resolution.
- Task 52: Signature object parsing compatibility.
- Task 53: Profile cross-check + improved mismatch diagnostics.
- Task 54: Regression tests across all above areas.

## Progress Notes
- Completed: Task 50 (manifest permission alias normalization in store models for `network.outbound|inbound` and `mqtt.client`).
- Completed: Task 51 (catalog release resolution now supports `channels` schema with `stable|beta|nightly` and legacy `releases[]` fallback).
- Pending: Tasks 52-54.

## Sequencing
1. Implement manifest normalization first (local correctness + low blast radius).
2. Add catalog channel parsing and release selection fallback.
3. Extend signature metadata parsing.
4. Add profile cross-check diagnostics.
5. Add/refresh tests and validate full store install paths.

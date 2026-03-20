# Phase 3 Internal Rename Audit

Status: In progress
Last updated: 2026-03-20

## Audit Summary

Remaining `Synthia` / `synthia` references fall into these buckets.

## Active Rename Targets

These are appropriate for Phase 3 cleanup:

- product-facing frontend/package metadata
- internal browser event ids used by onboarding flows
- notification source ids used in internal popup/event/state flows
- operator-facing script output and examples
- active docs still describing `Synthia` as the current platform brand
- test fixtures that only reflect those product-facing surfaces

## Intentional Legacy Holdouts

These are intentionally left unchanged for now:

- API token audiences such as `synthia-core`
- trust payload `paired_core_id` defaults
- env var names prefixed with `SYNTHIA_`
- systemd unit filenames such as `synthia-backend.service`
- repo/module path names such as `backend/synthia_supervisor`
- generated runtime state in `backend/var/`

## Historical Or Reference-Only Material

These should remain historical or be clearly separated from active docs:

- migration reports for earlier phases
- standards docs that record older contract shapes
- temp/reference planning docs under `docs/temp-ai-node/`
- older audit/report artifacts

## Cleanup Checklist

- update active product-facing strings to Hexe
- update active docs to stop describing `Synthia` as current-state branding
- update tests for the renamed product-facing behavior
- add validation to catch reintroduction of active `Synthia` branding
- document intentional legacy holdouts explicitly

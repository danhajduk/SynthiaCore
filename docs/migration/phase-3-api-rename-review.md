# Phase 3 API And Technical Contract Rename Review

Status: Implemented
Last updated: 2026-03-20

## Reviewed Areas

- API route paths
- API payload fields
- service token audiences
- trust payload core identifiers
- MQTT client ids and related runtime defaults
- systemd unit filenames
- env var names

## Decisions

### Leave As-Is For Now

- `/api/...` route paths remain unchanged
- service token audiences remain `synthia-core`
- trust payload `paired_core_id` remains `synthia-core`
- env vars remain `SYNTHIA_*`
- systemd unit filenames remain `synthia-*.service`
- repo/module paths such as `backend/synthia_supervisor` remain unchanged

Reason:
- these are compatibility-sensitive technical contracts or operational identifiers
- renaming them now would create churn beyond the scope of the product-facing cleanup phase

### Safe Renames Applied In This Phase

- internal app window event id for onboarding approval
- frontend package metadata
- notification/debug source ids used in internal app flows
- product-facing docs, script output, and display labels

## Deferred Follow-Up

If a later phase wants to rename technical contracts, it should be treated as a dedicated compatibility migration with:

- explicit alias/deprecation plan
- versioned rollout notes
- restart/redeployment guidance
- integration impact checklist

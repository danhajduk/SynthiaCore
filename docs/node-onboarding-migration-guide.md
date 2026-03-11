# Node Onboarding Migration Guide

Status: Planned
Last updated: 2026-03-11

## Purpose

This guide defines migration steps from legacy AI-node-specific onboarding routes to global node onboarding and registration routes.

## Route Migration

Use canonical global routes:

- `POST /api/system/nodes/onboarding/sessions`
- `GET /api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=...`
- `GET /api/system/nodes/registrations`
- `GET /api/system/nodes/registrations/{node_id}`

Legacy compatibility routes remain temporarily available:

- `POST /api/system/ai-nodes/onboarding/sessions`
- `GET /api/system/ai-nodes/onboarding/sessions/{session_id}/finalize?node_nonce=...`
- plus equivalent approval/list/get/reject aliases under `/api/system/ai-nodes/onboarding/sessions/*`

## Deprecation Behavior

Legacy AI-node alias routes emit:

- `Deprecation: true`
- `Sunset: 2026-09-30`
- `Warning: 299 ... deprecated ...`

## Sunset Plan

1. Through 2026-06-30: alias routes remain active, warnings enabled.
2. Through 2026-09-30: warnings continue; operators should complete migration to global routes.
3. After 2026-09-30: legacy AI-node alias routes are candidates for removal in a major compatibility cleanup release.

## Client Migration Checklist

1. Switch onboarding start/finalize calls to `/api/system/nodes/onboarding/sessions*`.
2. Consume canonical response fields (`node_name`, `node_type`, `node_software_version`) and keep `requested_*` only as temporary fallback.
3. Update operator links to `/onboarding/registrations/approve`.
4. Validate that bootstrap consumers use canonical endpoint keys (`register_session`, `registrations`) while tolerating legacy keys during transition.

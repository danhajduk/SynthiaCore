# MQTT Embedded Architecture (Target)

Last Updated: 2026-03-09 06:36 US/Pacific

## Goal

Synthia MQTT is targeted as embedded Core-managed infrastructure, not as a standalone remote addon provisioning dependency.

## Architecture Target

- Core remains source of truth for MQTT authority state (principals, grants, setup, policy).
- MQTT broker runtime artifacts (config/auth/ACL) are generated from Core-owned state.
- MQTT remains async/event plane for platform visibility and retained state distribution.
- Deterministic control transactions remain HTTP API-first.

## Loading Model

Target model:
- Embedded component under Core addon conventions:
  - `addons/mqtt/backend/addon.py`
  - `addons/mqtt/frontend/index.ts`
- Platform role is protected: MQTT behaves as platform-managed embedded addon/infrastructure, not a normal removable feature.

Current implementation note:
- Existing code still contains standalone/registered addon provisioning assumptions (`/api/system/mqtt/registrations/*` provision/revoke paths).
- Migration tasks track removal of those assumptions.

## Phase Boundaries

Phase 1 in-scope:
- Core-owned authority model
- embedded runtime reconciliation
- reserved namespace policy
- bootstrap-only anonymous access

Phase 4 (not Phase 1):
- External broker bridging

## Control-Plane Rule

Implemented and retained:
- HTTP APIs are the deterministic control plane.
- MQTT topics are async/event transport; they are not the primary request/response control channel.

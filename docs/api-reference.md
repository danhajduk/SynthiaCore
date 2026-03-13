# API Reference

All routes are mounted by `backend/app/main.py`.

## Conventions

- Admin-protected endpoints require admin authentication/session.
- Some route families include compatibility aliases for legacy clients.
- MQTT routes are mounted under `/api/system`.

## Core System APIs

Status: Implemented

- Health and stats:
  - `GET /api/health`
  - `GET /api/system/stats/current`
  - `GET /api/system-stats/current`
  - `GET /api/system/stack/summary`
- Settings and repo/system status:
  - `GET /api/system/settings`
  - `PUT /api/system/settings/{key}`
  - `GET /api/system/repo/status`
- Events/services:
  - `GET /api/system/events`
  - `POST /api/system/nodes/onboarding/sessions`
  - `GET /api/system/nodes/onboarding/sessions` (admin session/token required)
  - `GET /api/system/nodes/onboarding/sessions/{session_id}` (admin session/token required)
  - `POST /api/system/nodes/onboarding/sessions/{session_id}/approve` (admin session/token required)
  - `POST /api/system/nodes/onboarding/sessions/{session_id}/reject` (admin session/token required)
  - `GET /api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=...`
  - `GET /api/system/nodes/registrations` (admin session/token required)
  - `GET /api/system/nodes/registrations/{node_id}` (admin session/token required)
  - `DELETE /api/system/nodes/registrations/{node_id}` (admin session/token required)
  - `POST /api/system/nodes/registrations/{node_id}/revoke` (admin session/token required; `/untrust` alias preserved for compatibility)
  - `GET /api/system/nodes/registry` (admin session/token required; includes capability/governance/readiness status fields)
  - `POST /api/system/nodes/capabilities/declaration` (trusted node token required via `X-Node-Trust-Token`)
  - `POST /api/system/nodes/providers/capabilities/report` (trusted node token required via `X-Node-Trust-Token`; provider/model capability report ingestion)
  - `GET /api/system/nodes/providers/routing-metadata` (admin session/token required; model cost/latency + node availability view)
  - `GET /api/system/nodes/providers/model-policy` (admin session/token required)
  - `PUT /api/system/nodes/providers/model-policy/{provider}` (admin session/token required)
  - `DELETE /api/system/nodes/providers/model-policy/{provider}` (admin session/token required)
  - `GET /api/system/nodes/governance/current?node_id=...` (trusted node token required via `X-Node-Trust-Token`)
  - `POST /api/system/nodes/governance/refresh` (trusted node token required; version-aware governance refresh)
  - `GET /api/system/nodes/operational-status/{node_id}` (node trust token or admin session/token; lightweight lifecycle/capability/governance status)
  - `POST /api/system/nodes/telemetry` (trusted node token required; runtime lifecycle/governance signal ingestion)
  - `GET /api/system/nodes/capabilities/profiles` (admin session/token required)
  - `GET /api/system/nodes/capabilities/profiles/{profile_id}` (admin session/token required)
  - `POST /api/services/register`
  - `GET /api/services/resolve`

## Addon APIs

Status: Implemented

- Addon inventory/runtime:
  - `GET /api/addons`
  - `GET /api/addons/errors`
  - `GET /api/system/addons/runtime`
- Registry/admin:
  - `GET /api/addons/registry`
  - `POST /api/addons/registry/{addon_id}/register`
  - `GET /api/admin/addons/registry`
- Install sessions:
  - `POST /api/addons/install/start`
  - `POST /api/addons/install/{session_id}/permissions/approve`
  - `POST /api/addons/install/{session_id}/deployment/select`
  - `POST /api/addons/install/{session_id}/configure`
  - `POST /api/addons/install/{session_id}/verify`

## MQTT APIs

Status: Implemented (broad), Partial (future phases)

Representative routes under `/api/system`:
- setup/control: `/mqtt/status`, `/mqtt/setup-summary`, `/mqtt/setup/apply`, `/mqtt/setup/test-connection`, `/mqtt/setup-state`
- runtime: `/mqtt/runtime/health`, `/mqtt/runtime/start`, `/mqtt/runtime/stop`, `/mqtt/runtime/init`, `/mqtt/runtime/rebuild`, `/mqtt/runtime/config`
- approvals/principals/users: `/mqtt/registrations/*`, `/mqtt/principals*`, `/mqtt/users*`, `/mqtt/generic-users*`
- observability/audit: `/mqtt/noisy-clients*`, `/mqtt/observability`, `/mqtt/audit`
- debug: `/mqtt/debug/*`
- notification dev hook: `POST /mqtt/debug/notifications/test-flow` (admin token required; only active when `NOTIFICATION_DEBUG_ENABLED=true`)

Deprecated/legacy compatibility endpoints:
- `/api/system/runtime/*` aliases mirror `/api/system/mqtt/runtime/*` for compatibility.
- mixed snake/camel compatibility aliases are preserved in selected principal endpoints.
- `/api/system/ai-nodes/onboarding/sessions*` aliases mirror global node onboarding routes and emit `Deprecation` + `Sunset` headers.

## Auth and User APIs

Status: Implemented

- Admin session:
  - `POST /api/admin/session/login`
  - `POST /api/admin/session/login-user`
  - `GET /api/admin/session/status`
  - `POST /api/admin/session/logout`
- Admin users:
  - `GET /api/admin/users`
  - `POST /api/admin/users`
  - `DELETE /api/admin/users/{username}`
- Service token:
  - `POST /api/auth/service-token`
  - `POST /api/auth/service-token/rotate`

## Runtime, Scheduler, Health APIs

Status: Implemented

- Scheduler queue/lease/history routes under `/api/system/scheduler/*`.
- Stack/system health and metrics endpoints under `/api/system/*` and `/api/system-stats/*`.
- Store lifecycle and status routes under `/api/store/*`.

## Planned

Status: Planned

- Formal OpenAPI-focused endpoint stability tiers.
- Explicit deprecation lifecycle metadata per endpoint group.

## See Also

- [Core Platform](./core-platform.md)
- [MQTT Platform](./mqtt-platform.md)
- [Notifications Bus](./notifications.md)
- [Auth and Identity](./auth-and-identity.md)
- [Runtime and Supervision](./runtime-and-supervision.md)
- [Node Onboarding API Contract](./node-onboarding-api-contract.md)
- [Node Trust Activation Payload Contract](./node-trust-activation-payload-contract.md)
- [Node Phase 2 Lifecycle Contract](./node-phase2-lifecycle-contract.md)
- [Node Onboarding Migration Guide](./node-onboarding-migration-guide.md)

# MQTT Embedded Phase 1 Runbook

Last Updated: 2026-03-09 06:37 US/Pacific

## Where State Lives

Core authority state:
- `var/mqtt_integration_state.json`
  - setup/readiness
  - principals
  - grants

Audit and observability:
- `var/mqtt_authority_audit.db`
- `var/mqtt_observability.db`

## Where Generated Runtime Files Live

Rendered/applied runtime artifacts:
- `var/mqtt_runtime/live/*`
  - broker config references
  - listener config
  - ACL artifacts
  - auth references

## Readiness and Degraded Mode

Operational checks:
- `GET /api/system/mqtt/status`
- `GET /api/system/mqtt/setup-summary`
- `GET /api/system/mqtt/health`

Degraded indicators:
- `effective_status.status = degraded`
- `effective_status.reasons` includes setup/runtime causes
- `setup.setup_error` contains current setup/reconcile error

## Credential/Grant Rotation and Re-Issue

Current Phase 1 authority operations:
- approve/update grant scope:
  - `POST /api/system/mqtt/registrations/approve`
- apply active authority state:
  - `POST /api/system/mqtt/registrations/{addon_id}/provision`
- revoke:
  - `POST /api/system/mqtt/registrations/{addon_id}/revoke`

## Apply/Rollback Behavior

Pipeline:
- validates generated artifacts
- stages artifacts
- promotes to live
- reloads/restarts runtime
- rolls back if runtime stays unhealthy

Audit records are written on apply success/failure/rollback.

## Phase 1 Scope Boundaries

Included:
- embedded Core-owned authority model
- ACL/config/runtime foundation
- startup reconcile
- degraded-state reporting

Not included:
- external broker bridging automation
- full broker-provider runtime integration beyond boundary foundations
- automated noisy-client enforcement

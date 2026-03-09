# MQTT Embedded Migration Gap Note

Last Updated: 2026-03-09 06:36 US/Pacific

## Scope

This note audits current MQTT code paths in Core and marks where current behavior assumes a standalone/registered MQTT addon workflow.

## Reviewed Areas

- `/api/system/mqtt/*` router: `backend/app/system/mqtt/router.py`
- approval/provision/revoke service: `backend/app/system/mqtt/approval.py`
- setup-state/setup-summary models + persistence:
  - `backend/app/system/mqtt/integration_models.py`
  - `backend/app/system/mqtt/integration_state.py`
- main wiring and default state path:
  - `backend/app/main.py`
  - default `var/mqtt_integration_state.json`
- external provisioning dependency assumptions:
  - env paths `SYNTHIA_MQTT_PROVISION_PATH`, `SYNTHIA_MQTT_REVOKE_PATH`
  - control addon lookup via `registry.registered["mqtt"]`

## Reusable As-Is

- API-first control-plane boundary (`/api/system/mqtt/*`) can stay.
- setup-state persistence model and JSON store (`var/mqtt_integration_state.json`) are reusable as transitional authority state.
- topic-scope validation and reserved namespace checks in `topic_policy.py` remain useful.
- MQTT manager status/test/restart + retained info-topic publish behavior can remain.

## Must Refactor For Embedded MQTT Infrastructure

- `MqttRegistrationApprovalService._call_control_plane(...)` currently requires a remote addon base URL and posts to addon endpoints; embedded model should remove this remote HTTP dependency.
- grant lifecycle states (`approved -> provisioned/revoked/error`) are currently tied to remote provisioning/revoke calls and should move to Core-owned authority/apply semantics.
- `setup-summary` currently reports `last_provisioning_errors`; naming and semantics should shift toward embedded apply/runtime readiness errors.
- reconcile flow (`reconcile(...)`) currently reprovisions through remote addon calls when enabled; embedded mode should reconcile Core authority state against generated/runtime broker artifacts.

## Deprecate But Temporarily Preserve (Compatibility)

- Endpoints:
  - `POST /api/system/mqtt/registrations/{addon_id}/provision`
  - `POST /api/system/mqtt/registrations/{addon_id}/revoke`
- Internal fields:
  - `provision_contract`
  - `last_provisioned_at`
  - `last_revoked_at`
  - `last_provisioning_errors` (summary output key)
- Environment variables:
  - `SYNTHIA_MQTT_PROVISION_PATH`
  - `SYNTHIA_MQTT_REVOKE_PATH`
  - `SYNTHIA_MQTT_CONTROL_ADDON_ID`

Compatibility approach:
- Keep routes/fields temporarily but back them with Core-owned embedded authority actions during migration.

# MQTT Bootstrap Contract (Phase 1)

Last Updated: 2026-03-09 06:37 US/Pacific

## Topic

- `synthia/bootstrap/core` (retained publish target for bootstrap announcement contract)

## Access Rule

- Anonymous clients:
  - subscribe allowed only to exact bootstrap topic
  - publish denied
  - wildcard subscribe denied

## Payload Contract

Backend model reference:
- `backend/app/system/mqtt/integration_models.py` -> `MqttBootstrapAnnouncement`

Payload fields:
- `topic`
- `bootstrap_version`
- `core_id`
- `core_name`
- `api_base`
- `onboarding_endpoints`
- `onboarding_mode`
- `emitted_at`

## Security Boundary

- Payload must remain non-sensitive.
- Do not include secrets, credentials, or private key material.

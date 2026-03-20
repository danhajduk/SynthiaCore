# Phase 3 Completion Report

Status: Implemented
Completed on: 2026-03-20

## Outcome

Phase 3 completed the internal/product-facing rename cleanup that was safe to land without breaking compatibility-sensitive technical contracts.

The repository now prefers `Hexe` branding across active product-facing UI text, active operator-facing docs, package metadata, MQTT setup UI copy, onboarding browser event ids, and internal notification source ids used by app-facing flows.

## Completed Work

- added the canonical migration plan in `phase-3-internal-rename-hexe.md`
- added the audit and contract-decision docs for intentional legacy holdouts
- updated frontend package metadata to `hexe-frontend`
- renamed onboarding popup window event id to `hexe.node_onboarding.decided`
- updated active MQTT setup UI copy from `Synthia MQTT` to `Hexe MQTT`
- updated internal notification source ids from `synthia-core` to `hexe-core` for product-facing notification flows
- refreshed active architecture/node/operator docs that still described `Synthia` as current branding
- updated bootstrap/update examples to use Hexe-facing wording
- added `scripts/validate_hexe_branding.py` to catch reintroduction of active legacy branding

## Intentional Legacy Holdouts

The following remain intentionally unchanged in this phase:

- `SYNTHIA_*` env var names
- service token audiences such as `synthia-core`
- trust payload `paired_core_id`
- systemd unit filenames such as `synthia-backend.service`
- repo/module paths such as `backend/synthia_supervisor`
- generated runtime state under `backend/var/`

These are compatibility-sensitive and require a dedicated migration phase if changed later.

## Verification

Completed verification for the changed Phase 3 surface:

- `python3 scripts/validate_hexe_branding.py`
- `python3 -m py_compile backend/app/core/notification_producer.py backend/app/core/notification_debug.py backend/app/system/worker/runner.py scripts/validate_hexe_branding.py`
- `cd backend && PYTHONPATH=. .venv/bin/pytest -q tests/test_platform_identity.py tests/test_notification_bridge.py tests/test_notification_consumer.py tests/test_notification_schema.py tests/test_notification_producer.py tests/test_mqtt_embedded_ui_routes.py`
- `cd frontend && npm run build`

## Deferred Items

No product-facing route alias migration was needed in this phase.

Any future attempt to rename API route paths, token audiences, env vars, systemd unit ids, or repo/module paths should be handled as a compatibility migration rather than additional cosmetic cleanup.

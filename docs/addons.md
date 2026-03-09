# Addons Reference (Core + Addon Workspace)

Last Updated: 2026-03-09 06:37 US/Pacific

This document is the single handoff reference for building, registering, and operating addons with Synthia Core.

## 1) Addon Types

- Embedded addon:
  - Lives under Core `addons/<id>/`
  - Loaded directly by backend discovery.
- Registered remote addon:
  - Runs as separate service.
  - Registered in Core registry and accessed via proxy.

## 2) Embedded Addon Contract

Expected package layout:

- Backend entry: `addons/<id>/backend/addon.py`
- Frontend entry: `addons/<id>/frontend/index.ts`

Backend entrypoint exports:

- `addon` object containing metadata + router.

Frontend entrypoint exports:

- `meta`
- `routes`
- `navItem`

## 3) Remote Addon Service Contract

Core expects these addon endpoints on the addon service itself:

- `GET /api/addon/meta`
- `GET /api/addon/health`
- `POST /api/addon/config`

These are used by register/verify/configure flows.

## 4) Core Registry APIs

Base URL examples assume Core is reachable at `http://<core-host>:<core-port>`.

Public read APIs:

- `GET /api/addons/registry`
- `GET /api/addons/registry/{addon_id}`

Admin APIs (require admin auth):

- `POST /api/addons/registry/{addon_id}/register`
- `POST /api/addons/registry/{addon_id}/configure`
- `POST /api/addons/registry/{addon_id}/verify`
- `GET /api/admin/addons/registry`
- `POST /api/admin/addons/registry`
- `DELETE /api/admin/addons/registry/{addon_id}`

## 5) Admin Auth

Admin endpoints accept either:

- Header token: `X-Admin-Token: <SYNTHIA_ADMIN_TOKEN>`
- Admin session cookie from:
  - `POST /api/admin/session/login`

Login payload:

```json
{ "token": "<SYNTHIA_ADMIN_TOKEN>" }
```

## 6) Registration and Verification Flow

1. Register addon base URL:

```bash
curl -X POST "http://<core>/api/addons/registry/mqtt/register" \
  -H "X-Admin-Token: <token>" \
  -H "Content-Type: application/json" \
  -d '{"base_url":"http://<addon-host>:<addon-port>","name":"Synthia MQTT","version":"0.1.0"}'
```

2. Optional configure:

```bash
curl -X POST "http://<core>/api/addons/registry/mqtt/configure" \
  -H "X-Admin-Token: <token>" \
  -H "Content-Type: application/json" \
  -d '{"config":{"key":"value"}}'
```

3. Verify health:

```bash
curl -X POST "http://<core>/api/addons/registry/mqtt/verify" \
  -H "X-Admin-Token: <token>"
```

4. Read back registry state:

```bash
curl "http://<core>/api/addons/registry/mqtt"
```

## 7) Unregister Flow

```bash
curl -X DELETE "http://<core>/api/admin/addons/registry/mqtt" \
  -H "X-Admin-Token: <token>"
```

Returns 404 if addon is not registered.

## 8) Addon Proxy Paths

Once registered, Core proxies addon APIs/UI via:

- API proxy: `/api/addons/{addon_id}/...`
- UI proxy legacy path: `/ui/addons/{addon_id}/...`
- UI proxy alias path: `/addons/{addon_id}/...`

## 9) MQTT Discovery (Optional but Recommended)

Addon can auto-publish to broker:

- Retained announce: `synthia/addons/{addon_id}/announce`
- Health updates: `synthia/addons/{addon_id}/health`

Core subscribes and updates registry `last_seen`/health metadata from these topics.

Control-plane boundary:
- Use Core HTTP APIs for control actions (registration approval/provision/revoke/setup-state/admin flows).
- Use MQTT topics for asynchronous events and runtime visibility, not deterministic control transactions.

## 10) MQTT Broker Setup in Core

Embedded MQTT direction note:
- MQTT is being migrated toward platform-managed embedded infrastructure semantics.
- Existing registration/provision/revoke API routes remain for compatibility while Core-owned embedded authority state is adopted.

Core MQTT host/port is selected by settings keys (not by registry API):

- `mqtt.mode` = `local` or `external`
- `mqtt.local.host`, `mqtt.local.port`
- `mqtt.external.host`, `mqtt.external.port`

Apply config via settings API and restart MQTT manager:

- `PUT /api/system/settings/mqtt.mode`
- `PUT /api/system/settings/mqtt.external.host`
- `PUT /api/system/settings/mqtt.external.port`
- `POST /api/system/mqtt/restart`

## 11) Troubleshooting

- `registered_addon_not_found` during register call:
  - Ensure Core includes the route-precedence fix where registry routes are evaluated before proxy catch-all.
- 401 on admin endpoints:
  - Verify `X-Admin-Token` or login cookie.
- Verify failures:
  - Confirm addon implements `/api/addon/health` and service is reachable from Core.
- TLS warning in registry entry:
  - Non-HTTPS remote `base_url` may set `tls_warning` by design.

## 12) MQTT Contract Reference

- Core MQTT platform contract: [mqtt-contract.md](./mqtt-contract.md)

## 13) Standalone Desired/Rebuild Contract

- Addons do not push updates directly to supervisor; Core writes `desired.json`.
- Supervisor has no direct notify API and discovers desired changes on polling reconcile.
- Core writes `desired_revision`; unchanged revision on same running version is treated as no-op by supervisor.
- Compose/runtime input changes on same version can trigger supervisor compose regeneration when Core writes updated desired runtime + revision.
- `force_rebuild=true` can be used in desired payload to force one rebuild/recreate cycle for the current `desired_revision`.
- Current manifest runtime defaults used by Core for desired runtime are limited to `ports` and `bind_localhost`.
- Multi-service compose topology declarations in manifest are not developed in current schema/runtime.

## 14) Addon UI Styling

- Core theme token system contract: [theme.md](./theme.md)
- Addon author styling and isolation guide: [addon-ui-styling.md](./addon-ui-styling.md)

# Addon Platform

## Addon Models

### Embedded Addons

Status: Implemented

- Discovered and loaded into Core runtime using addon metadata/contracts.
- UI surfaces are integrated through Core frontend routes and addon proxy embedding.
- MQTT policy and coordination for embedded addon integrations remain Core-owned.

### Standalone Addons

Status: Partially implemented

- Standalone artifact contracts and desired/runtime documents exist.
- Runtime realization depends on supervisor/runtime boundaries and deployment context.
- This is a compatibility-era runtime path, not the canonical external extension model for new platform work.

## Discovery and Registry

Status: Implemented

- Core registry supports discovery, status, and admin lifecycle actions.
- Store/install pipeline integrates with registry and status endpoints.

Primary surfaces:
- `/api/addons`
- `/api/addons/errors`
- `/api/addons/registry*`
- `/api/admin/addons/registry*`
- `/api/store/status*`

Registered addon records expose canonical Core-side UI proxy metadata:
- `ui_enabled`
- `ui_base_url`
- `ui_mode`

Registry UI metadata rules:
- `ui_base_url` must be an absolute `http://` or `https://` URL when present
- legacy registered addons safely backfill UI metadata from `base_url`
- `ui_mode` defaults to `server`
- missing UI metadata remains explicit through `ui_enabled = false`

## Addon Lifecycle

Status: Implemented

- Install sessions: start -> permissions -> deployment -> configure -> verify.
- Runtime lifecycle actions include enable/register/configure/verify and uninstall/update via store flows.

## Store and Manifest Relationship

Status: Implemented

- `addon-manifest.schema.json` governs addon manifest structure.
- Store lifecycle validates package layout and compatibility before install/update.
- Desired/runtime files are used for standalone state handoff.

## Distributed Addons

Status: Partially implemented

- Distributed addons are the same compatibility-era runtime category as standalone addons in the current documentation layout.
- Standalone packaging, compatibility, and remediation references now live under `docs/addons/standalone-archive/`.

## Canonical Boundary

Status: Implemented

- Embedded addons are the canonical addon model for functionality that stays inside Core.
- Nodes are the canonical model for external functionality and execution surfaces.
- Supervisor is the host-local runtime authority that can realize compatibility-era standalone runtime state, but it does not replace Nodes as the external platform boundary.

## Deprecated/Superseded Guidance

Status: Archived Legacy

- Prior split docs (`addons.md`, `addon-system.md`, `standalone-addon.md`) are archived after transfer into this canonical file.

## See Also

- [Core Platform](../core/api/core-platform.md)
- [API Reference](../core/api/api-reference.md)
- [Frontend and UI](../core/frontend/frontend-and-ui.md)
- [Data and State](../core/api/data-and-state.md)
- [addon-lifecycle.md](./addon-lifecycle.md)
- [standalone-archive/README.md](./standalone-archive/README.md)

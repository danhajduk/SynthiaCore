# Addon Platform

## Addon Models

### Embedded Addons

Status: Implemented

- Discovered and loaded into Core runtime using addon metadata/contracts.
- UI surfaces are integrated through Core frontend routes and addon proxy embedding.

### Standalone Addons

Status: Partial

- Standalone artifact contracts and desired/runtime documents exist.
- Runtime realization depends on supervisor/runtime boundaries and deployment context.

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

Status: Partial

- Distributed addon references and policy docs remain under `docs/distributed_addons/`.
- Canonical ownership remains here; implementation maturity varies by capability.

## Deprecated/Superseded Guidance

Status: Archived Legacy

- Prior split docs (`addons.md`, `addon-system.md`, `standalone-addon.md`) are archived after transfer into this canonical file.

## See Also

- [Core Platform](../fastapi/core-platform.md)
- [Platform Architecture](../platform-architecture.md)
- [API Reference](../fastapi/api-reference.md)
- [Frontend and UI](../frontend/frontend-and-ui.md)
- [Data and State](../fastapi/data-and-state.md)

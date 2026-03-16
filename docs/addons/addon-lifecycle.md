# Addon Lifecycle

This document describes the addon lifecycle as implemented in the current repository.

## Discovery

Status: Implemented

- Core discovers backend addons from `backend/app/addons/discovery.py`.
- Discovered embedded addons are loaded into the Core-managed runtime and can expose UI and API surfaces through Core.
- Registered remote addons are tracked separately in the addon registry.

## Registry Lifecycle

Status: Implemented

- Core persists enabled and disabled state plus the registered addon list.
- Registered addons are validated against the required addon contract before they are accepted.
- MQTT announce and health messages can refresh registered addon metadata and status.

Primary code:
- `backend/app/addons/registry.py`

## Install Session Lifecycle

Status: Implemented

Install sessions are stored in `backend/app/addons/install_sessions.py` and move through these states:

- `pending_permissions`
- `pending_deployment`
- `discovered`
- `registered`
- `configured`
- `verified`
- `installed`
- `error`

Current transitions verified in code:

- `start` -> `pending_permissions`
- `approve_permissions` -> `pending_deployment`
- `mark_discovered` converts matching `pending_deployment` sessions to `discovered`
- `configure` moves `discovered` to `registered`, then to `configured`
- `verify` moves `configured` to `verified` on healthy results, otherwise to `error`

`installed` is present in the allowed state set, but a separate transition into that state is not verifiable from the current repository methods.

## Embedded vs Standalone

Status: Partially implemented

- Embedded addons run inside the Core-managed runtime and are the active local integration model.
- Standalone addons reuse the Core lifecycle authority, but runtime realization depends on supervisor/runtime boundaries and addon store flows.
- New external functionality should be modeled as Nodes rather than as standalone addons.
- Standalone package-profile guidance and remediation docs now live under `docs/addons/standalone-archive/`.

## See Also

- [addon-platform.md](./addon-platform.md)
- [standalone-archive/README.md](./standalone-archive/README.md)
- [../supervisor/runtime-and-supervision.md](../supervisor/runtime-and-supervision.md)
- [../core/api/api-reference.md](../core/api/api-reference.md)

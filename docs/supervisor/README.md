# Supervisor Docs

This is the canonical entrypoint for Supervisor documentation in the `Core -> Supervisor -> Nodes` structure.

## Status

Status: Implemented

Supervisor currently spans:

- `backend/synthia_supervisor/`
- `backend/app/system/runtime/`
- `backend/app/supervisor/`

## Current Responsibilities

- standalone addon runtime supervision
- desired vs runtime reconciliation
- compose-based service realization for host-local standalone workloads
- migration-foundation route exposure through:
  - `GET /api/supervisor/health`
  - `GET /api/supervisor/info`
  - `GET /api/supervisor/resources`
  - `GET /api/supervisor/runtime`
  - `GET /api/supervisor/nodes`
  - `POST /api/supervisor/nodes/{node_id}/start`
  - `POST /api/supervisor/nodes/{node_id}/stop`
  - `POST /api/supervisor/nodes/{node_id}/restart`

Broader host-local resource and lifecycle ownership is Partially implemented.

## Included Docs

- [runtime-and-supervision.md](./runtime-and-supervision.md)
- [domain-models.md](./domain-models.md)

## See Also

- [../architecture.md](../architecture.md)
- [../addon-standalone/README.md](../addon-standalone/README.md)
- [../addons/addon-platform.md](../addons/addon-platform.md)

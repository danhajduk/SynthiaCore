# Hexe Supervisor Docs

This is the canonical entrypoint for Hexe Supervisor documentation in the `Core -> Supervisor -> Nodes` structure.

## Status

Status: Implemented

Supervisor currently spans:

- `backend/synthia_supervisor/`
- `backend/app/system/runtime/`
- `backend/app/supervisor/`

## Current Responsibilities

- host monitoring through `HostResourceSummary`, `SupervisorHealthSummary`, and `SupervisorRuntimeSummary`
- admission context reporting through `GET /api/supervisor/admission`
- standalone addon lifecycle control through:
  - `GET /api/supervisor/nodes`
  - `POST /api/supervisor/nodes/{node_id}/start`
  - `POST /api/supervisor/nodes/{node_id}/stop`
  - `POST /api/supervisor/nodes/{node_id}/restart`
- standalone runtime state reporting through:
  - `GET /api/supervisor/health`
  - `GET /api/supervisor/info`
  - `GET /api/supervisor/resources`
  - `GET /api/supervisor/runtime`
- compose-based realization for host-local standalone addon workloads

## Explicit Non-Goals

Status: Implemented

Supervisor does not own these areas in the current repository state:

- OS administration
- package management
- general service management outside Hexe-managed runtimes
- firewall and network policy management
- non-Hexe workload orchestration

## Future Expansion Path

Status: Not developed

Supervisor may grow into these areas later, but they are not implemented today:

- broader host-local workload supervision
- managed worker execution ownership
- richer reconciliation loops
- runtime backends beyond the current compose-based standalone path

## Included Docs

- [runtime-and-supervision.md](./runtime-and-supervision.md)
- [domain-models.md](./domain-models.md)
- [lifecycle-control.md](./lifecycle-control.md)
- [workload-admission.md](./workload-admission.md)
- [architecture-gap.md](./architecture-gap.md)

## See Also

- [../architecture.md](../architecture.md)
- [../addons/standalone-archive/README.md](../addons/standalone-archive/README.md)
- [../addons/addon-platform.md](../addons/addon-platform.md)

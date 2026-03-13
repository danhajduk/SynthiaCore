# Supervisor Docs

This folder contains the standalone runtime and supervision documentation for Synthia Core.

## Included Docs

- [runtime-and-supervision.md](./runtime-and-supervision.md)
  Runtime ownership, supervisor boundaries, and standalone realization flow.

## Code Boundary

Status: Implemented

- Supervisor code lives under `backend/synthia_supervisor/`.
- Core-side runtime and handoff logic lives under `backend/app/system/runtime/`.

## See Also

- [../addon-standalone/README.md](../addon-standalone/README.md)
- [../fastapi/data-and-state.md](../fastapi/data-and-state.md)

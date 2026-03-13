# FastAPI Docs

This folder contains the Core backend documentation for the FastAPI application and the HTTP control-plane it exposes.

## Included Docs

- [core-platform.md](./core-platform.md)
  Core backend responsibilities, service ownership, and control-plane boundaries.
- [api-reference.md](./api-reference.md)
  Route-family reference for the current backend API surface.
- [auth-and-identity.md](./auth-and-identity.md)
  Authentication and identity behavior for admin, service, and platform actors.
- [data-and-state.md](./data-and-state.md)
  Persistent and runtime state references used by Core services.

## Code Boundary

Status: Implemented

- Main app assembly lives under `backend/app/`.
- Route families are mounted from `backend/app/system/`, `backend/app/addons/`, and `backend/app/store/`.

## See Also

- [../architecture.md](../architecture.md)
- [../mqtt/mqtt-platform.md](../mqtt/mqtt-platform.md)
- [../frontend/frontend-and-ui.md](../frontend/frontend-and-ui.md)

# Embedded Addon Docs

This folder contains documentation for embedded addons that run inside the Core-managed runtime.

## Included Docs

- [addon-platform.md](./addon-platform.md)
  Canonical addon platform reference covering embedded and standalone lifecycle ownership.

## Code Boundary

Status: Implemented

- Core addon discovery and registry code lives under `backend/app/addons/`.
- Embedded addon UI and API integration is handled by Core backend and frontend surfaces.

## See Also

- [../frontend/frontend-and-ui.md](../frontend/frontend-and-ui.md)
- [../addon-standalone/README.md](../addon-standalone/README.md)

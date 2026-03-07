# Synthia Core Documentation

Last Updated: 2026-03-07 15:42 US/Pacific

## Documentation Contract

This documentation set reflects behavior verified in the repository code.

If a capability is not explicitly documented as implemented, treat it as **Not developed**.

## What Core Is

Synthia Core is the orchestration/control plane built from:
- Backend FastAPI services (`backend/app/*`)
- Frontend React UI (`frontend/src/*`)
- Scheduler, store, auth, policy, telemetry, and addon registry modules

Core orchestrates system behavior but does not directly run standalone services.
Standalone service runtime execution is handled by supervisor + Docker compose.

## Ownership Boundaries

Core owns:
- API surface and admin/session flows
- Scheduler state and lifecycle APIs
- Addon registry, install sessions, store/catalog flows
- Desired state generation for standalone services
- Canonical standalone runtime aggregation (`desired.json` + `runtime.json` + Docker metadata)
- UI routing, settings, metrics, and store pages

Core does not own:
- Direct container runtime execution for standalone services
- Docker daemon lifecycle
- Supervisor internals beyond writing desired/runtime intent files and reading status

## System Relationship Map

```text
Core
├── Backend (FastAPI)
│   ├── API / Auth / Users / Settings
│   ├── Scheduler
│   ├── Store + Catalog
│   ├── Addon Registry + Install Sessions
│   └── Policy / Telemetry / MQTT
├── Frontend (React)
│   ├── Home / Store / Addons / Settings
│   └── Admin session-gated routes
└── Addon Runtime Integration
    ├── Core writes desired.json and stages addon.tgz
    ├── Supervisor reconciles runtime.json and compose execution
    └── Core runtime API exposes normalized standalone runtime status
```

## Documentation Index

- [Architecture Map](./architecture-map.md)
- [Backend](./backend.md)
- [Frontend](./frontend.md)
- [Auth and Users](./auth-and-users.md)
- [Scheduler](./scheduler.md)
- [Addon System](./addon-system.md)
- [Store and Catalog](./store.md)
- [API Overview](./api.md)
- [Data Model](./data-model.md)
- [Deployment](./deployment.md)
- [Supervisor](./supervisor.md)
- [Standalone Addon](./standalone-addon.md)

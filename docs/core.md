# Synthia Core Documentation

Last Updated: 2026-03-09 06:36 US/Pacific

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
- Service discovery APIs (`/api/services/resolve`, `/api/services/register`) and service-token gated registration policy
- Platform event foundation (`/api/system/events`) with lifecycle event emission hooks
- Desired state generation for standalone services
- Canonical standalone runtime aggregation (`desired.json` + `runtime.json` + Docker metadata)
- UI routing, settings, metrics, and store pages
- Structured settings control-plane UX (General, Platform, Connectivity, Addon Registry, Security/Access, Developer tools)
- Home dashboard full-stack status aggregation (health, connectivity, sampled speed snapshot semantics)

Core does not own:
- Direct container runtime execution for standalone services
- Docker daemon lifecycle
- Supervisor internals beyond writing desired/runtime intent files and reading status
- Durable cross-process event streaming infrastructure (current event queue is in-memory in backend process)

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
│   ├── Home dashboard / Store / Addons / Settings
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
- [MQTT Integration Contract](./mqtt-contract.md)
- [MQTT Embedded Migration Gap Note](./mqtt-embedded-gap-note.md)
- [MQTT Embedded Architecture (Target)](./mqtt-embedded-architecture.md)
- [MQTT Embedded Addon/Platform Contract](./mqtt-embedded-contract.md)
- [Data Model](./data-model.md)
- [Deployment](./deployment.md)
- [Supervisor](./supervisor.md)
- [Standalone Addon](./standalone-addon.md)

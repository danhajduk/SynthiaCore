# Platform Architecture

## Architecture Summary

Synthia is organized as a Core control plane with subsystem routers/services and addon-facing runtime boundaries.

Status: Implemented (core topology), Partial (long-term standalone harmonization)

## Core Control Plane

Status: Implemented

- App bootstraps through `backend/app/main.py`.
- Core wires system services: settings, users, scheduler, events, policy, telemetry, store, and MQTT.
- Background loops handle stats sampling, catalog refresh, addon health refresh, and MQTT runtime supervision.

## Subsystem Boundaries

### API Layer

Status: Implemented

- FastAPI route groups mounted under `/api`, `/api/system`, `/api/admin`, `/api/store`, `/api/services`, `/api/auth`, `/api/policy`, `/api/telemetry`.

### Addon Models

Status: Partial

- Embedded addon pattern is active and operational.
- Standalone addon runtime and supervision patterns exist, but historical constraints and evolution notes are retained as archived legacy context.

### Runtime Boundaries

Status: Implemented

- Runtime controls exist for scheduler and MQTT runtime boundary.
- Desired/runtime model split exists for standalone addon artifacts and supervisor state handoff.

### Supervisor Role

Status: Implemented

- Supervisor ownership remains focused on runtime realization and service process/container lifecycle boundaries.
- Core remains authority owner for desired state and policy.

### Scheduler and Worker Role

Status: Implemented

- Pull-based lease flow with queue and heartbeat model.
- Worker lifecycle stages (request/heartbeat/complete/report/revoke) are represented in system scheduler APIs.

## Embedded vs Standalone Distinction

### Embedded Platform Services

Status: Implemented

- Core-owned service execution and embedded UI integration through addon proxy routes.

### Standalone Services

Status: Partial

- Standalone addon contract and desired/runtime artifacts remain supported.
- Compatibility and mismatch notes moved to archive after canonical migration.

## Architecture Risks and Drift Controls

Status: Implemented

- Canonical docs now centralize architecture ownership.
- Legacy docs moved to archive to reduce contradictory guidance.

## See Also

- [Overview](./overview.md)
- [Core Platform](./fastapi/core-platform.md)
- [Runtime and Supervision](./supervisor/runtime-and-supervision.md)
- [Addon Platform](./addon-embedded/addon-platform.md)
- [MQTT Platform](./mqtt/mqtt-platform.md)

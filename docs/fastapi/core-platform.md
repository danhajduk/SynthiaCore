# Core Platform

## Core Responsibilities

Status: Implemented

- Boot application and mount all subsystem routers.
- Own control-plane state and admin policy decisions.
- Coordinate addon registry, runtime status, and platform health aggregation.
- Coordinate embedded MQTT authority/runtime startup and reconciliation.
- Coordinate notification publisher, bridge, local consumer, and startup/debug notification flows.

Code anchors:
- `backend/app/main.py`
- `backend/app/system/*`

## Setup / Readiness / Status Model

Status: Implemented

- Core tracks runtime setup/readiness for MQTT integration via integration state store.
- Setup summary and health/degraded API surfaces are exposed under `/api/system/mqtt/*`.
- Background supervision loop updates degraded/ready state and publishes audit/observability events.

## Authority Boundaries

Status: Implemented

- Core is source of truth for:
  - admin users/session control
  - policy grants/revocations
  - MQTT principal authority state and effective access
- Runtime providers execute generated artifacts but do not own policy truth.

## Interaction With Runtime and Supervisor

Status: Partial

- Core owns desired behavior and invokes runtime boundaries (`ensure_running`, `start`, `stop`, `rebuild`).
- Standalone runtime service and supervisor-related contracts remain active, with behavior segmented in runtime docs.

## Scheduler Integration

Status: Implemented

- Core wires scheduler engine/store/history and exposes lease and queue APIs.
- Cleanup and metrics loops are hosted in Core startup background tasks.

## Known Legacy Context

Status: Archived Legacy

- Prior supervisor/standalone mismatch analysis was transferred from task artifact docs and retained in archive for historical traceability.

## See Also

- [Platform Architecture](../platform-architecture.md)
- [Runtime and Supervision](../supervisor/runtime-and-supervision.md)
- [Notifications Bus](../mqtt/notifications.md)
- [API Reference](./api-reference.md)
- [Auth and Identity](./auth-and-identity.md)

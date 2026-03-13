# Runtime and Supervision

## Runtime Ownership

Status: Implemented

- Core owns desired-state intent and runtime orchestration hooks.
- Runtime boundaries execute concrete start/stop/rebuild/health flows.
- Supervisor/standalone runtime model remains active for standalone addon execution paths.

## Startup and Supervision

Status: Implemented

- Core startup initializes service stores, registry, MQTT manager/runtime boundary, and background supervision loops.
- MQTT runtime supervision handles unhealthy recovery and config-missing self-heal pathways.

## Scheduler and Worker Flow

Status: Implemented

- Job flow: submit -> lease request -> heartbeat -> complete/report/revoke.
- Queue APIs and history stats provide operational visibility.
- History cleanup and scheduler metrics are automated background concerns.

## Deployment and Runtime Boundaries

Status: Partial

- Deployment environment, paths, and service dependencies are defined in code and existing runbooks.
- Standalone vs embedded boundary behavior is implemented but still evolving.

## Restart Semantics Boundary

Status: Implemented

- Backend process supervision is owned by systemd user service template (`systemd/user/synthia-backend.service.in`) with:
  - `Restart=always`
  - `RestartSec=2`
- Embedded MQTT docker runtime restart policy is owned by runtime boundary config (`backend/app/system/mqtt/runtime_boundary.py`) via:
  - `SYNTHIA_MQTT_DOCKER_RESTART_POLICY` (default `no`)
- This means backend process auto-restart and MQTT container auto-restart are separate controls.
- Operators should not assume backend restart policy implies docker container restart policy.

## Store and Runtime Interaction

Status: Implemented

- Store lifecycle writes desired/runtime-linked state for addon deployment outcomes.
- Runtime status and diagnostics APIs expose deployment/runtime realization status.

## Planned

Status: Planned

- Further unification of standalone and embedded runtime observability surfaces.
- Additional runtime policy enforcement and lifecycle guardrails.

## See Also

- [Platform Architecture](../platform-architecture.md)
- [Core Platform](../fastapi/core-platform.md)
- [Operators Guide](../operators-guide.md)
- [Data and State](../fastapi/data-and-state.md)

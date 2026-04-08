# Runtime and Supervision

## Current Responsibilities

Status: Implemented

- Core owns desired-state intent and calls into Supervisor for host-local standalone runtime actions where implemented.
- Supervisor reports host resources and process state through `/api/supervisor/health`, `/api/supervisor/resources`, and `/api/supervisor/runtime`.
- Supervisor produces admission context through `/api/supervisor/admission`.
- Supervisor lists standalone addon runtime state and performs start/stop/restart actions through `/api/supervisor/nodes` and the corresponding node action routes.
- Supervisor exposes runtime state and runtime-apply actions for Supervisor-managed helper runtimes (currently `cloudflared`) through:
  - `GET /api/supervisor/runtime/{runtime_id}`
  - `POST /api/supervisor/runtime/{runtime_id}/apply`
- Supervisor now also owns a separate runtime contract for real Nodes through:
  - `POST /api/supervisor/runtimes/register`
  - `POST /api/supervisor/runtimes/heartbeat`
  - `GET /api/supervisor/runtimes`
  - `GET /api/supervisor/runtimes/{node_id}`
  - `POST /api/supervisor/runtimes/{node_id}/start`
  - `POST /api/supervisor/runtimes/{node_id}/stop`
  - `POST /api/supervisor/runtimes/{node_id}/restart`
- Supervisor owns a Core-hosted runtime contract for Core services, addons, and aux containers through:
  - `POST /api/supervisor/core/runtimes/register`
  - `POST /api/supervisor/core/runtimes/heartbeat`
  - `GET /api/supervisor/core/runtimes`
  - `GET /api/supervisor/core/runtimes/{runtime_id}`
  - `POST /api/supervisor/core/runtimes/{runtime_id}/start`
  - `POST /api/supervisor/core/runtimes/{runtime_id}/stop`
  - `POST /api/supervisor/core/runtimes/{runtime_id}/restart`
- Supervisor computes heartbeat freshness for real Nodes as `online`, `stale`, `offline`, or `error` based on the locally tracked runtime record.
- Standalone addon realization is compose-based today through `compose_up` and `compose_down` in `backend/app/supervisor/service.py`.
- Supervisor API service probes are available at `/health` and `/ready` on the standalone Supervisor API server.

## Aux Container Heartbeats

Status: Implemented

- Core-hosted services and aux containers must send heartbeats to the local Supervisor over the Unix socket at `/run/hexe/supervisor.sock`.
- Heartbeats for Core-owned runtimes are sent via `POST /api/supervisor/core/runtimes/heartbeat` and should include runtime metadata relevant to the aux service.
- Core services are monitor-only and will be rejected when start/stop/restart actions are attempted.
- Core-owned addons and aux services/containers are declared as `manage` to allow Supervisor action intent tracking.
- Each aux container must include a lightweight heartbeat script or sidecar that posts to the Supervisor socket.

## Restart Semantics Boundary

Status: Implemented

- Backend process supervision is owned by systemd user service template (`systemd/user/hexe-backend.service.in`) with:
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
- Core Node registry views can now consume Supervisor-owned runtime truth for real Nodes in read-only form without moving governance ownership out of Core.

## Explicit Non-Goals

Status: Implemented

Supervisor does not currently implement:

- OS administration
- package management
- general service supervision outside Hexe-managed runtimes
- firewall or network policy control
- non-Hexe orchestration
- arbitrary third-party container lifecycle control outside explicit Hexe-managed runtimes

## Future Expansion Path

Status: Not developed

Future growth can extend this boundary toward:

- broader host-local workload supervision
- managed worker execution ownership
- richer reconciliation loops
- runtime backends beyond compose

## See Also

- [../architecture.md](../architecture.md)
- [Operators Guide](../operators-guide.md)
- [../core/README.md](../core/README.md)

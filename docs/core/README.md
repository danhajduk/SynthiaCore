# Core Docs

This is the canonical entrypoint for Hexe Core documentation in the `Core -> Supervisor -> Nodes` structure.

## Status

Status: Implemented

Core is currently implemented across:

- `backend/app/main.py`
- `backend/app/core/`
- `backend/app/api/`
- `backend/app/system/`
- `frontend/`

## Core Responsibilities

- API hosting
- operator UI hosting
- embedded addon lifecycle authority
- scheduler orchestration and workload admission
- MQTT authority and messaging policy
- trusted-node trust, governance, and telemetry authority

## Extension Rules

- Embedded addons are Core-local extensions and stay inside the Core runtime.
- External functionality should be modeled through Nodes.
- Supervisor realizes host-local runtime intent for compatibility-era standalone workloads, but that does not replace Nodes as the canonical external platform boundary.

## Current Core Documentation Map

- [./api/README.md](./api/README.md)
- [./frontend/README.md](./frontend/README.md)
- [./scheduler/README.md](./scheduler/README.md)
- [./node-budget-assignment-flow.md](./node-budget-assignment-flow.md)
- [../workers/README.md](../workers/README.md)
- [../addons/README.md](../addons/README.md)
- [../mqtt/README.md](../mqtt/README.md)

## Migration Structure

The folders `docs/core/api/`, `docs/core/frontend/`, and `docs/core/scheduler/` now hold the re-homed Core API, frontend, and scheduler docs.

## Workload Rule

- Keep scheduler ownership in Core for admission, policy, and orchestration.
- Do not describe Core as the long-term execution runtime boundary when the behavior is actually worker-, Supervisor-, or Node-side.
- Treat host-local worker/process execution management as Supervisor-owned, even when compatibility helpers still live in Core-era module paths.

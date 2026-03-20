# Hexe Core Architecture

This document describes the current repository architecture as implemented in code. The migration foundation now treats `Core`, `Supervisor`, and `Nodes` as first-class domains without removing the existing subsystem layouts.

Compatibility note: public display names and active MQTT topic roots now use Hexe naming. Some route paths, package/module identifiers, env vars, and service unit filenames still retain legacy forms where compatibility or operational stability matters.

## Domain Boundaries

### Core

Status: Implemented

Core is assembled in `backend/app/main.py` and currently spans:

- `backend/app/core/`
- `backend/app/api/`
- `backend/app/system/`
- `frontend/`

Current Core responsibilities include:

- API hosting
- UI hosting
- embedded addon lifecycle authority
- scheduler orchestration and workload admission
- MQTT authority and runtime coordination
- trusted-node trust and governance authority

### Supervisor

Status: Implemented

Supervisor is the host-local runtime realization boundary and currently spans:

- `backend/synthia_supervisor/`
- `backend/app/system/runtime/`
- `backend/app/supervisor/`

Current top-level routes:

- `GET /api/supervisor/health`
- `GET /api/supervisor/info`
- `GET /api/supervisor/admission`

Broader host resource and lifecycle ownership remains Partially implemented.

### Nodes

Status: Implemented

Nodes are trusted external systems that connect to Core. Current node code boundaries are:

- `backend/app/system/onboarding/`
- `backend/app/nodes/`

Current top-level routes:

- `GET /api/nodes`
- `GET /api/nodes/{node_id}`

These routes reuse the existing canonical node registration payload shape rather than introducing a second schema.

## Extension Boundary

Status: Implemented

- Embedded addons remain inside Core and are the active local extension model under `backend/app/addons/`.
- Supervisor owns host-local runtime realization and compatibility-era standalone runtime state, but that host-local path is not the canonical external extension model.
- Nodes are the canonical external functionality and execution model. New external compute or integration surfaces should be expressed through node onboarding, trust, capability, governance, and telemetry flows.
- Core remains the MQTT authority for messaging policy and node-facing connectivity material.

## Workload Boundary

Status: Implemented

- Scheduler queueing, admission, and lease orchestration remain Core responsibilities.
- The scheduler does not own host-local runtime execution as a platform boundary.
- Current worker runners are execution clients that consume Core-issued leases.
- Host-local worker/process execution management now aligns to the Supervisor boundary, even where compatibility code still lives under `backend/app/system/worker/`.
- Supervisor now provides the admission context Core uses for host readiness and managed execution-target availability.
- Supervisor is the target host-local runtime authority, and Nodes are the canonical external execution layer.

## Cross-Domain Flow

### Core -> Supervisor

Status: Implemented

Core writes and inspects standalone runtime intent through the current runtime and supervisor code paths. Supervisor realizes host-local standalone workloads outside the main Core process.

### Core -> Nodes

Status: Implemented

Core remains the trust, governance, and operational authority for nodes. Nodes onboard through Core, receive trust and governance material from Core, and report capabilities and telemetry back into Core-owned services.

### Core Internal Subsystems

Status: Implemented

Major active Core subsystems remain:

- addons and store
- scheduler and workers
- MQTT platform services
- auth, users, policy, telemetry, audit, and settings

## Foundation Route Map

The migration foundation currently adds:

- `GET /api/architecture`
- `GET /api/supervisor/health`
- `GET /api/supervisor/info`
- `GET /api/nodes`
- `GET /api/nodes/{node_id}`

These routes are mounted in `backend/app/main.py` and are implemented through the new wrappers in:

- `backend/app/architecture/`
- `backend/app/supervisor/`
- `backend/app/nodes/`

## Related Docs

- [core/README.md](./core/README.md)
- [supervisor/README.md](./supervisor/README.md)
- [nodes/README.md](./nodes/README.md)
- [overview.md](./overview.md)

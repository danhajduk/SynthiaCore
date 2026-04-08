# Hexe AI Platform Overview

Hexe AI is a modular automation and AI platform for home and edge environments. In the current repository, the platform is moving toward a `Core -> Supervisor -> Nodes` structure that makes control-plane, host-runtime, and external-execution boundaries explicit.

Compatibility note: the public-facing product name is now Hexe AI, and the active MQTT namespace has also moved to `hexe/...`. API route paths and Python package names still retain their existing internal forms.

## Domain Model

### Core

Status: Implemented

Core is the control plane. It currently owns:

- API hosting
- operator UI hosting
- embedded addon lifecycle authority
- scheduler orchestration and workload admission
- MQTT authority and messaging policy
- trusted-node trust, governance, and telemetry authority

### Supervisor

Status: Implemented

Supervisor is the host-local runtime authority. In current code this spans:

- `backend/synthia_supervisor/`
- `backend/app/system/runtime/`
- `backend/app/supervisor/`
- `backend/app/supervisor/server.py`
- `systemd/user/synthia-supervisor-api.service.in`

Current top-level routes:

- `GET /health`
- `GET /ready`
- `GET /api/supervisor/health`
- `GET /api/supervisor/info`

Broader host-local lifecycle ownership remains Partially implemented.

### Nodes

Status: Implemented

Nodes are trusted external systems that connect to Core. Current implemented flows include onboarding, registration, trust activation, capability declaration, governance issuance, and telemetry reporting.

Current top-level routes:

- `GET /api/nodes`
- `GET /api/nodes/{node_id}`

## Current Platform Shape

```text
Operator UI
  |
Core
  |- API, scheduler, MQTT, addons, trust, governance
  |- Supervisor handoff and runtime visibility
  \- Node orchestration authority

Supervisor
  \- host-local standalone runtime realization

Nodes
  \- trusted external capability providers and execution systems
```

## Extension Boundary

- Embedded addons remain inside Core.
- Supervisor realizes host-local runtime state for standalone compatibility paths.
- Nodes are the canonical external extension and execution model.
- MQTT remains Core-owned and participates in cross-domain coordination where implemented.

## Workload Boundary

- Core scheduler logic admits and orchestrates work.
- Execution currently happens through leased worker/runtime clients outside the Core admission loop where implemented.
- Supervisor now provides host/runtime admission context back into Core scheduling.
- Supervisor and Nodes are the target runtime boundaries for host-local and external execution.

## Related Docs

- [core/README.md](./core/README.md)
- [supervisor/README.md](./supervisor/README.md)
- [nodes/README.md](./nodes/README.md)
- [architecture.md](./architecture.md)

# Hexe Core

Hexe Core is the control-plane service for the Hexe AI platform. This repository now documents the migration foundation for the `Core -> Supervisor -> Nodes` structure while preserving the current runtime and API surface.

Compatibility note: Phase 0 is a cosmetic rebrand only. Internal identifiers such as `synthia/...` MQTT topics, `/api/...` paths, Python module names, and systemd unit filenames remain unchanged during this phase.

## Start Here

- [docs/index.md](docs/index.md)
- [docs/overview.md](docs/overview.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/core/README.md](docs/core/README.md)
- [docs/supervisor/README.md](docs/supervisor/README.md)
- [docs/nodes/README.md](docs/nodes/README.md)
- [docs/mqtt/README.md](docs/mqtt/README.md)

## Domain Summary

### Core

Status: Implemented

Core currently spans:

- `backend/app/main.py`
- `backend/app/core/`
- `backend/app/api/`
- `backend/app/system/`
- `frontend/`

Hexe Core owns API hosting, UI hosting, embedded addon lifecycle authority, scheduler orchestration and workload admission, MQTT authority, and trusted-node governance flows.

### Supervisor

Status: Implemented

Supervisor currently spans:

- `backend/synthia_supervisor/`
- `backend/app/system/runtime/`
- `backend/app/supervisor/`

Current responsibilities:

- `GET /api/supervisor/health`
- `GET /api/supervisor/info`
- `GET /api/supervisor/resources`
- `GET /api/supervisor/runtime`
- `GET /api/supervisor/admission`
- `GET /api/supervisor/nodes`
- `POST /api/supervisor/nodes/{node_id}/start`
- `POST /api/supervisor/nodes/{node_id}/stop`
- `POST /api/supervisor/nodes/{node_id}/restart`

Current non-goals:

- OS administration
- package management
- general service management outside Hexe-managed runtimes
- firewall/network policy
- non-Hexe orchestration

### Nodes

Status: Implemented

Node services currently span:

- `backend/app/system/onboarding/`
- `backend/app/nodes/`

The migration foundation exposes:

- `GET /api/nodes`
- `GET /api/nodes/{node_id}`

These routes reuse the existing canonical node registration payload shape.

## Extension Boundary

- Embedded addons stay inside the Core runtime.
- Supervisor realizes host-local runtime intent and compatibility-era standalone runtime state.
- External functionality is node-first in the migration structure. New external capability providers should be modeled as Nodes, not as standalone addons.
- MQTT remains Core-owned and is used as part of Core-to-node and Core-to-addon coordination where implemented.

## Workload Boundary

- Core scheduler APIs own queueing, admission, and orchestration decisions.
- Execution happens through worker/runtime clients outside that Core admission path where implemented today.
- Supervisor and Nodes are the target runtime boundaries for host-local and external execution respectively.

## Repository Layout

- `backend/app/`: FastAPI app, Core control-plane services, and migration domain routers
- `backend/synthia_supervisor/`: standalone runtime supervision and desired/runtime reconciliation
- `frontend/`: React operator UI
- `docs/`: canonical repository documentation
- `scripts/`: development and bootstrap helpers
- `systemd/`: service templates and runtime integration

## Local Development

Backend dependencies:

- `backend/requirements.txt`

Frontend dependencies:

- `frontend/package.json`

Typical development flow:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 9001
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev -- --port 5173
```

## Current Architecture Note

The repository is additive-first during migration. Core, Supervisor, and Nodes are now first-class documentation and API domains, but existing subsystem layouts remain active until later migration tasks re-home or retire them.

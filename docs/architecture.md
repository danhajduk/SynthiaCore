# Synthia Core Architecture

This document describes the architecture of the Synthia Core repository specifically. It explains how the Core application is structured internally and how the main subsystems relate inside this codebase, rather than documenting the full Synthia ecosystem.

## Scope

This document covers the internal architecture of Synthia Core as implemented in this repository.

It includes:
- Core control-plane responsibilities
- subsystem ownership boundaries
- major runtime and communication flows
- high-level source mapping for architecture-relevant code

It does not include:
- platform-wide overview material already covered in [overview.md](./overview.md)
- install steps that belong in [../README.md](../README.md)
- full API details that belong in [fastapi/api-reference.md](./fastapi/api-reference.md)
- deep payload/schema references that belong in subsystem docs such as [mqtt/mqtt-platform.md](./mqtt/mqtt-platform.md) or [mqtt/notifications.md](./mqtt/notifications.md)

Document boundary summary:
- [overview.md](./overview.md): platform-wide overview
- this file: Core internal architecture
- subsystem docs: deeper implementation contracts and references

## Architectural Responsibilities

Synthia Core acts as the control-plane for the repository.

Its current responsibilities include:
- API hosting through the FastAPI application in `backend/app/main.py`
- frontend serving and integration with the React application in `frontend/`
- runtime state coordination for platform services and standalone runtime status
- addon lifecycle authority for discovery, registry, store, install, update, uninstall, and verification flows
- scheduler and worker orchestration for queueing, leasing, completion, and history
- MQTT platform authority for setup, principal lifecycle, policy, runtime reconciliation, bootstrap, and notifications
- trusted node integration for onboarding, capability declaration, governance, and telemetry
- telemetry, audit, and health aggregation across Core-managed services

## Major Subsystems

### Core Backend

The Core backend owns application assembly and control-plane orchestration.

What it owns:
- FastAPI app creation and route mounting
- startup and shutdown lifecycle
- Core-owned stores and service wiring
- background maintenance and supervision loops

What it depends on:
- subsystem modules under `backend/app/system/`
- addon and store modules under `backend/app/addons/` and `backend/app/store/`
- runtime and supervisor-facing contracts for standalone flows

How it interacts with other parts:
- serves the frontend and operator APIs
- coordinates scheduler, MQTT, addon, store, and node services
- exposes the main boundary other components call into

### Frontend

The frontend is the operator-facing UI for the platform.

What it owns:
- shell layout and navigation
- Core settings, status, addon, and store pages
- addon UI embedding and route integration

What it depends on:
- backend APIs
- addon metadata and route contracts

How it interacts with other parts:
- consumes backend state and lifecycle endpoints
- presents Core-managed and addon-integrated workflows to operators

### MQTT Platform Services

The MQTT subsystem provides shared messaging authority and runtime behavior.

What it owns:
- MQTT authority state and principal lifecycle
- topic policy, ACL compilation, and approval flows
- runtime boundary management and startup reconciliation
- bootstrap publication and MQTT observability
- internal notification publishing, local consumption, and external bridging

What it depends on:
- Core settings and state stores
- runtime boundary implementations
- audit and observability stores

How it interacts with other parts:
- provides messaging infrastructure for Core, addons, and nodes
- feeds health and runtime signals back into Core
- supports internal and external notification flows

### Scheduler

The scheduler handles queued work and lease-based execution.

What it owns:
- job submission and queue state
- lease request, heartbeat, and completion flows
- scheduler history and summary statistics

What it depends on:
- scheduler stores
- metrics provider input from Core

How it interacts with other parts:
- provides execution work for worker-side flows
- contributes runtime and health information to the wider platform

### Workers

Worker support is the Core-side execution helper layer around scheduled jobs.

What it owns:
- worker-side support code in `backend/app/system/worker/`
- execution helpers tied to scheduler-issued work

What it depends on:
- scheduler jobs and leases

How it interacts with other parts:
- consumes scheduler work
- represents the execution-side companion to the scheduler subsystem

### Supervisor

The supervisor is the standalone runtime realization layer.

What it owns:
- desired/runtime handling for standalone workloads
- compose-oriented runtime orchestration
- runtime transition support for standalone services

What it depends on:
- desired-state intent written by Core/store flows
- runtime metadata and deployment artifacts

How it interacts with other parts:
- receives desired/runtime handoff from Core
- realizes standalone workloads outside the main Core process

### Addon Platform

The addon platform is the main extension surface for embedded and standalone addons.

What it owns:
- addon discovery and registry
- install-session and store lifecycle behavior
- embedded addon integration contracts
- standalone addon handoff into runtime/supervisor paths

What it depends on:
- Core lifecycle authority
- store/catalog validation
- runtime/supervisor support for standalone deployments

How it interacts with other parts:
- embedded addons extend the in-process platform
- standalone addons extend the platform through supervised runtime boundaries

### Node Integration

Node integration supports trusted external systems that join the Synthia platform.

What it owns:
- onboarding sessions and approval flow
- node trust activation and registration
- capability declaration and governance distribution
- node telemetry ingestion and operational status

What it depends on:
- Core trust and policy authority
- API contracts and bootstrap discovery surfaces

How it interacts with other parts:
- extends the platform beyond the local host
- keeps Core as the authoritative trust and governance boundary

## Control Flow

### API/UI Flow

The frontend talks to the Core backend over HTTP. The backend mounts the platform routers, coordinates Core-owned services, and returns the data used by the operator UI. Embedded addon UI and Core pages share the same overall host-managed application surface.

### Scheduler/Job Flow

Jobs are submitted into the scheduler, queued by priority, leased to workers, heartbeated while active, and then completed or expired. History and metrics are recorded and surfaced back through Core APIs and dashboards.

### Addon Lifecycle Flow

Core discovers embedded addons locally and manages addon registry and store lifecycle flows centrally. Install sessions move through permission, deployment, configuration, and verification phases. Standalone addon flows extend this with desired/runtime handoff into supervisor-managed realization.

### Standalone Runtime/Supervisor Flow

Core and store flows create desired-state intent for standalone runtime behavior. Supervisor/runtime components read that intent, reconcile it into concrete runtime actions, and expose runtime state that Core reads back for APIs and UI visibility.

### Node Onboarding/Governance Flow

Nodes start with onboarding session APIs, are approved by Core, receive trust activation material, become registered participants, and then interact through capability, governance, and telemetry flows controlled by Core.

### MQTT Event/Notification Flow

Core owns the MQTT authority and runtime layer, subscribes to platform-relevant traffic, and coordinates bootstrap, observability, and notification behavior. Internal notifications are published on canonical internal topics, consumed locally for desktop display when appropriate, and bridged into simplified external topics such as Home Assistant.

## Runtime Boundaries

The main runtime boundaries in Synthia Core are:

- in-process Core services
  - backend app, stores, scheduler, MQTT coordination, and platform logic
- embedded addons
  - integrated into Core-managed backend and UI surfaces
- supervised standalone services
  - realized outside the main Core process through runtime and supervisor boundaries
- external trusted nodes
  - run outside the host-local Core runtime and integrate through Core-controlled APIs and messaging
- frontend vs backend boundary
  - the frontend is a separate application surface that consumes backend APIs rather than sharing backend state directly
- API vs MQTT boundary
  - API is the main control-plane boundary for authority and operator actions
  - MQTT is used where runtime messaging, bootstrap, observability, and notification/event transport are appropriate

## Extension Models

Synthia Core currently supports three main extension models.

### Embedded Addons

Embedded addons integrate most tightly with Core. They are discovered and loaded by Core and share the Core-managed runtime and UI/backend integration model.

### Standalone Addons

Standalone addons remain Core-managed from a lifecycle perspective, but are realized through desired/runtime state and supervised runtime execution rather than the same in-process boundary used by embedded addons.

### External Nodes

External nodes extend the platform beyond the local host. Core remains the authority for onboarding, trust, governance, and status, while nodes contribute capabilities and telemetry from outside the Core runtime boundary.

## Source Layout

High-level architectural source mapping:

- `backend/app/`
  - main Core application wiring and route assembly
- `backend/app/system/`
  - MQTT, scheduler, workers, auth, policy, telemetry, onboarding, and system services
- `backend/app/addons/`
  - addon discovery, registry, install-session, and proxy logic
- `backend/app/store/`
  - store/catalog, lifecycle, extraction, and audit flows
- `backend/app/core/`
  - shared Core helpers such as health, logging, and notification services
- `backend/synthia_supervisor/`
  - standalone runtime and supervisor implementation
- `frontend/`
  - React UI, shell, routes, and operator pages
- `scripts/`
  - bootstrap, dev, reload, update, and helper scripts
- `systemd/user/`
  - user service templates for backend, frontend, supervisor, and updater

## Related Documentation

- [index.md](./index.md)
- [overview.md](./overview.md)
- [fastapi/core-platform.md](./fastapi/core-platform.md)
- [mqtt/mqtt-platform.md](./mqtt/mqtt-platform.md)
- [supervisor/runtime-and-supervision.md](./supervisor/runtime-and-supervision.md)
- [addon-embedded/addon-platform.md](./addon-embedded/addon-platform.md)
- [fastapi/api-reference.md](./fastapi/api-reference.md)
- [mqtt/notifications.md](./mqtt/notifications.md)

## High-Level Diagram

```text
                    +----------------------+
                    |      Frontend        |
                    |   React operator UI  |
                    +----------+-----------+
                               |
                               | HTTP
                               v
+-----------------------------------------------------------------+
|                      Synthia Core Backend                        |
| API routers | state stores | addon lifecycle | node authority   |
| scheduler | MQTT services | notifications | health | telemetry  |
+-----------+----------------------+--------------------+----------+
            |                      |                    |
            | in-process           | MQTT/runtime       | desired/runtime
            v                      v                    v
   +----------------+   +---------------------+   +------------------+
   | Scheduler      |   | MQTT platform       |   | Supervisor       |
   | + Workers      |   | authority/runtime   |   | standalone flow  |
   +----------------+   +----------+----------+   +---------+--------+
                                   |                        |
                                   | MQTT                   | runtime realization
                      +------------+-------------+          v
                      |                          |   +------------------+
                      v                          v   | Standalone       |
             +-------------------+        +---------------------------+
             | Embedded Addons   |        | External Nodes            |
             | Core-integrated   |        | trusted remote systems    |
             +-------------------+        +---------------------------+
```

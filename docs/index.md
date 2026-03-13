# Synthia Core Documentation

This page is the navigation hub for the Synthia Core repository documentation. Use it to find the right document before going into subsystem-specific detail.

## Start Here

- [../README.md](../README.md)
  Repository entry point with the high-level explanation of what Synthia Core is, what it includes, and how to run or install it.
- [overview.md](./overview.md)
  Platform-level overview for readers who need wider Synthia context first.
- [architecture.md](./architecture.md)
  Internal architecture of the Synthia Core repository, including subsystem boundaries and control flows.

## Core Platform

- [fastapi/README.md](./fastapi/README.md)
  Backend documentation hub for the FastAPI control plane.
- [fastapi/core-platform.md](./fastapi/core-platform.md)
  Core control-plane responsibilities, ownership boundaries, and readiness model.
- [fastapi/api-reference.md](./fastapi/api-reference.md)
  API route-family reference for the backend mounted by Core.
- [frontend/README.md](./frontend/README.md)
  Frontend documentation hub for the React operator UI.
- [frontend/frontend-and-ui.md](./frontend/frontend-and-ui.md)
  Frontend structure and Core-managed UI surfaces.
- [fastapi/auth-and-identity.md](./fastapi/auth-and-identity.md)
  Authentication and identity references for admin, service, and platform actors.

## Runtime and Messaging

- [mqtt/README.md](./mqtt/README.md)
  Messaging documentation hub for MQTT and notifications.
- [mqtt/mqtt-platform.md](./mqtt/mqtt-platform.md)
  MQTT authority, runtime, bootstrap, and principal lifecycle documentation.
- [mqtt/notifications.md](./mqtt/notifications.md)
  Notification topics, routing behavior, local consumer rules, and bridge-owned external payloads.
- [supervisor/README.md](./supervisor/README.md)
  Standalone runtime and supervision documentation hub.
- [supervisor/runtime-and-supervision.md](./supervisor/runtime-and-supervision.md)
  Runtime ownership, supervision boundaries, and standalone runtime behavior.
- [fastapi/data-and-state.md](./fastapi/data-and-state.md)
  Persistent and runtime state references used across the platform.
- [overview.md](./overview.md)
  Includes the higher-level role of MQTT and runtime boundaries in the platform.

## Addons and Nodes

- [addon-embedded/README.md](./addon-embedded/README.md)
  Embedded addon documentation hub.
- [addon-embedded/addon-platform.md](./addon-embedded/addon-platform.md)
  Embedded and standalone addon models, lifecycle, and store relationships.
- [addon-standalone/README.md](./addon-standalone/README.md)
  Standalone addon runtime and packaging references.
- [distributed_addons/README.md](./distributed_addons/README.md)
  Distributed addon reference and policy-alignment baseline.
- [nodes/README.md](./nodes/README.md)
  Trusted-node documentation hub.
- [nodes/node-onboarding-registration-architecture.md](./nodes/node-onboarding-registration-architecture.md)
  Global onboarding and registration architecture for trusted nodes.
- [nodes/node-phase2-lifecycle-contract.md](./nodes/node-phase2-lifecycle-contract.md)
  Trusted-node capability, governance, and operational lifecycle references.

## Scheduler and Workers

- [scheduler/README.md](./scheduler/README.md)
  Scheduler landing page for queueing and lease-based execution docs.
- [workers/README.md](./workers/README.md)
  Worker landing page for execution helper docs.

## Operations and Development

- [operators-guide.md](./operators-guide.md)
  Operational guidance and runbook-style documentation.
- [development-guide.md](./development-guide.md)
  Development and documentation maintenance guidance for this repository.
- [ROADMAP.md](./ROADMAP.md)
  Active planning input for ongoing work.
- [documentation-migration-map.md](./documentation-migration-map.md)
  Documentation consolidation and migration tracking.

## Reference

- [document-index.md](./document-index.md)
  Broader canonical documentation map already maintained in this repository.
- [platform-architecture.md](./platform-architecture.md)
  Higher-level platform architecture reference beyond the Core-internal view.
- [addon-manifest.schema.json](./addon-manifest.schema.json)
  Addon manifest schema reference.
- [desired.schema.json](./desired.schema.json)
  Desired-state schema reference.
- [runtime.schema.json](./runtime.schema.json)
  Runtime-state schema reference.

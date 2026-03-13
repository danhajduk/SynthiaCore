# Synthia Overview

## Purpose

Synthia is a host-control platform for running and supervising addons with a shared Core control plane, scheduler, and integrated MQTT infrastructure.

## Platform Parts

- Core backend (`backend/app/main.py`) provides API, orchestration, and authority state.
- Frontend (`frontend/src`) provides operator/admin workflows and addon UI embedding.
- Addon system (`addons/`, registry, store) supports embedded and standalone runtime models.
- Runtime/supervision coordinates desired vs runtime state and health.
- MQTT platform provides authority, topics, bootstrap, ACL compilation, and runtime controls.

## Embedded vs Standalone Model

### Embedded

Status: Implemented

- Addon logic can be loaded directly into Core process/runtime and surfaced through Core UI proxy paths.
- Embedded MQTT runtime is controlled by Core using runtime boundary + startup reconciliation.

### Standalone

Status: Partial

- Standalone runtime contracts and desired/runtime files exist.
- Supervisor/runtime integration exists, with some legacy assumptions preserved in archived docs for historical context.

## Role of MQTT

Status: Implemented (Phase 1/2 foundation), Partial (future phases)

- Provides retained control-plane topic publishing and runtime visibility channels.
- Core owns principal lifecycle, effective-access generation, ACL compilation, and runtime apply/reconcile hooks.
- Future phases (policy expansion/federation/noisy-client automation) remain planned.

## Role of Core

Status: Implemented

- Core is source of truth for setup/readiness, authority policy state, and runtime orchestration.
- Core exposes operator/admin APIs for addons, MQTT, scheduler, auth, telemetry, policy, and health.
- Core enforces platform boundaries across users, principals, reserved topics, and addon lifecycle operations.

## Current Priorities (From Roadmap)

- Keep embedded MQTT and admin workflows stable.
- Preserve deterministic scheduler and runtime behavior.
- Maintain clean docs boundaries with canonical-first updates.
- Keep AI Node architecture documentation aligned between golden docs and the AI Node repo mapping policy.

## See Also

- [Platform Architecture](../platform-architecture.md)
- [Core Platform](../fastapi/core-platform.md)
- [MQTT Platform](../mqtt/mqtt-platform.md)
- [Document Index](../document-index.md)
- [AI Node Docs Mapping](../nodes/ai-node-docs-mapping.md)

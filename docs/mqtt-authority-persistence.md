# MQTT Authority Persistence Model (Design)

Last Updated: 2026-03-09 06:37 US/Pacific

## Scope

This document defines the Core-side source-of-truth persistence boundary for embedded MQTT authority.

## Current Baseline

Current Core persistence:
- `var/mqtt_integration_state.json` via `MqttIntegrationStateStore`
- includes:
  - setup/readiness fields
  - `active_grants`
  - `principals`

## Source Of Truth vs Generated Artifacts

Core source-of-truth state (authoritative):
- principals
- grants
- setup state/readiness
- audit/event records (design target for Phase 1 implementation tasks)
- broker readiness metadata

Generated runtime artifacts (non-authoritative):
- broker config files
- ACL files
- auth/password files
- rendered runtime manifests

Rule:
- Generated broker/runtime files must not be treated as canonical authority state.
- Reconciliation regenerates runtime artifacts from Core-owned source state.

## Migration Note

Current `var/mqtt_integration_state.json` is the transitional authority store.
Future tasks can migrate to structured DB-backed authority storage while preserving source-of-truth semantics.

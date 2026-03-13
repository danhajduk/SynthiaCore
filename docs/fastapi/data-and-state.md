# Data and State

## Persistent State Overview

Synthia persists control-plane state in SQLite and JSON documents.

Status: Implemented

## SQLite Stores

Status: Implemented

Observed active stores include:
- app settings (`APP_SETTINGS_DB`, default `var/app_settings.db`)
- users (`APP_USERS_DB`, default `var/users.db`)
- scheduler history (`SCHEDULER_HISTORY_DB`, default `var/scheduler_history.db`)
- telemetry usage (`TELEMETRY_USAGE_DB`, default `var/telemetry_usage.db`)
- MQTT authority audit/observability stores
- store audit persistence

## JSON State Files

Status: Implemented

Observed JSON-backed state includes:
- MQTT integration state (`var/mqtt_integration_state.json`)
- MQTT credential store (`var/mqtt_credentials.json`)
- node onboarding session state (`data/node_onboarding_sessions.json`)
- node onboarding archived terminal sessions (`data/node_onboarding_sessions.json.archive.jsonl`)
- global node registrations (`data/node_registrations.json`)
- AI Node trust issuance records (`data/node_trust_records.json`)
- policy grants/revocations (`var/policy_*.json`)
- service catalog and store source state
- standalone addon desired/runtime files

## Desired and Runtime Models

Status: Implemented

- Desired/runtime schema references:
  - [`desired.schema.json`](./desired.schema.json)
  - [`runtime.schema.json`](./runtime.schema.json)
- Core writes desired intent for runtime realization.
- Supervisor/runtime layers realize runtime state.

## Addon Manifest Model

Status: Implemented

- Canonical schema: [`addon-manifest.schema.json`](./addon-manifest.schema.json)
- Used by store/addon lifecycle validation and metadata handling.

## Authority State

Status: Implemented

- MQTT authority state includes setup/readiness fields, grants, and principal maps.
- Runtime-generated artifacts are derived outputs; authority JSON/DB state remains source of truth.

## Schema Ownership

Status: Implemented

- JSON schemas in `docs/*.schema.json` are canonical references for contract shape.
- Canonical docs reference schemas rather than duplicating full schema bodies.

## Planned

Status: Planned

- Unified migration framework for all JSON and SQLite contract evolution.
- Centralized schema registry with versioned cross-subsystem compatibility checks.

## See Also

- [Core Platform](./core-platform.md)
- [Runtime and Supervision](../supervisor/runtime-and-supervision.md)
- [MQTT Platform](../mqtt/mqtt-platform.md)
- [Addon Platform](../addon-embedded/addon-platform.md)

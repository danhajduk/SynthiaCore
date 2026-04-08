# Hexe Core JSON Schemas

This folder contains Core-owned JSON schema documents for the Hexe platform.

## What Is Covered

- Existing hand-written schema docs for node-facing onboarding, notification, lifecycle, and proxied UI contracts.
- Generated schema catalogs for Core-owned Pydantic API and model definitions in `backend/app/`.
- Store schemas for Core-owned persisted JSON files under `data/` and selected runtime state files under `backend/var/` and `var/`.

## What Is Not Covered

- Node-owned schemas that belong in node repositories.
- Secret-value stores whose shape is not a stable public contract.
- YAML or non-JSON configuration files.

## Main Groups

- Node-facing and MQTT-facing contracts:
  - `node_*`
  - `notification_*`
  - `proxied_ui_*`
- Core model catalogs:
  - `core.notifications.models.schema.json`
  - `nodes.*.schema.json`
  - `supervisor.models.schema.json`
  - `supervisor.api.schema.json`
  - `scheduler.models.schema.json`
  - `runtime.models.schema.json`
  - `stats.models.schema.json`
  - `edge.models.schema.json`
  - `mqtt.integration.models.schema.json`
  - `addons.models.schema.json`
  - `store.*.schema.json`
- Request-model catalogs:
  - `api.*.request-models.schema.json`
  - `system.*.request-models.schema.json`
  - `mqtt.router.request-models.schema.json`
- Persisted Core store contracts:
  - `node_*.store.schema.json`
  - `model_routing_registry.store.schema.json`
  - `provider_model_policy.store.schema.json`
  - `addons_*.store.schema.json`
  - `store_install_state.store.schema.json`
  - `edge_gateway.store.schema.json`
  - `mqtt_integration_state.store.schema.json`
  - `store_sources.store.schema.json`

## Notes

- Generated catalog files may include a `skipped_models` section when a Pydantic model contains runtime-only objects that cannot be expressed as JSON Schema.
- Store schemas document the owned on-disk payload shape used by Core persistence code. They are intended as contract references, not migration guarantees across all historical snapshots.

# Proxied UI Metadata

Status: Implemented (baseline fields), Partial (reserved extension fields)
Last updated: 2026-03-22

## Purpose

Defines the metadata Core uses to decide whether a node UI or addon UI can be proxied safely and how that UI should be mounted behind Core-owned public routes.

This document standardizes:

- required field meanings
- validation rules
- fail-safe defaults
- forward-compatible reserved fields for newer proxied UIs

## Baseline Implemented Fields

These fields are already present in the current registry/registration models and are used by the running proxy system.

### `ui_enabled`

- Type: `bool`
- Meaning: whether Core should consider the target UI publishable through the Core proxy
- Default: `false`
- Fail-safe behavior:
  - if `false`, Core must treat the UI as unavailable
  - if omitted, Core derives a safe value from whether a valid `ui_base_url` can be resolved

### `ui_mode`

- Type: `spa | server`
- Meaning: declares whether the upstream UI behaves like a client-side app or a server-rendered app
- Defaults:
  - nodes: `spa`
  - addons: `server`
- Validation:
  - unknown values fall back to the default for that target kind

### `ui_base_url`

- Type: absolute internal `http://` or `https://` URL
- Meaning: upstream base URL reachable by Core for the UI surface
- Default: `null`
- Validation:
  - must include `http` or `https`
  - must include a host
  - trailing slash is normalized away
- Safety rule:
  - this is an internal Core-facing origin, not a browser-facing public URL
  - browser code must never call it directly
- Fail-safe behavior:
  - if absent or invalid, Core must treat the UI as unavailable

### `ui_health_endpoint` (`ui_health_url` contract intent)

- Type: optional absolute internal `http://` or `https://` URL
- Meaning: optional health probe target for the UI upstream
- Default: `null`
- Naming note:
  - current code-backed models and APIs use `ui_health_endpoint`
  - task-planning language may refer to the same concept as `ui_health_url`
- Validation:
  - same URL normalization rules as `ui_base_url`
- Fail-safe behavior:
  - if absent, Core skips active health probing
  - if present and unhealthy, Core may fail closed into the UI fallback shell instead of forwarding

## Reserved Contract Fields

These fields are part of the proxied UI contract for new work even where they are not yet persisted or enforced across every existing registry path.

### `ui_supports_prefix`

- Type: `bool`
- Meaning: whether the UI is known to work when mounted below a Core-owned path prefix such as `/nodes/{node_id}/ui/` or `/addons/{addon_id}/`
- Intended default:
  - new UIs: `true`
  - legacy or unknown UIs: treat missing as `false` until compatibility is confirmed
- Safety rule:
  - Core should not advertise an unknown UI as fully compatible with prefixed mounting unless this behavior is confirmed

### `ui_entry_path`

- Type: relative path
- Meaning: entry path inside `ui_base_url` that Core should treat as the canonical UI shell
- Default: `/`
- Validation:
  - must resolve relative to `ui_base_url`
  - must not be an external absolute URL
- Safety rule:
  - this path must stay inside the upstream UI service

### `ui_websocket_enabled`

- Type: `bool`
- Meaning: whether the UI expects websocket traffic through the Core UI proxy surface
- Default: `false`
- Fail-safe behavior:
  - when missing, Core should not assume websockets are required
  - websocket-capable UIs should declare the field explicitly as the contract evolves

## Validation Rules

Core-side metadata handling must follow these rules:

- `ui_enabled` must default to `false`
- `ui_base_url` must be internal-only and must never be treated as a browser-visible public URL
- a target cannot be treated as proxyable when `ui_enabled = true` but `ui_base_url` is missing or invalid
- `ui_mode` must normalize to `spa` or `server`
- `ui_health_endpoint` is optional and must use the same absolute `http(s)` URL rules as `ui_base_url`
- reserved fields must fail safe when absent

## Defaults Summary

- `ui_enabled`: `false`
- `ui_mode`: `spa` for nodes, `server` for addons
- `ui_base_url`: `null`
- `ui_health_endpoint`: `null`
- `ui_supports_prefix`: treat missing as `false` unless compatibility is explicitly known
- `ui_entry_path`: `/`
- `ui_websocket_enabled`: `false`

## Current Model Coverage

Current code-backed registry/registration models expose:

- addons: `ui_enabled`, `ui_base_url`, `ui_mode`
- nodes: `ui_enabled`, `ui_base_url`, `ui_mode`, `ui_health_endpoint`

The reserved fields above define the forward contract for future metadata expansion and author guidance. Until they are persisted everywhere, missing values must be interpreted conservatively.

## See Also

- [Proxied UI Contract](../frontend/proxied-ui-contract.md)
- [Frontend and UI](../frontend/frontend-and-ui.md)
- [API Reference](./api-reference.md)
- [Addon Platform](../../addons/addon-platform.md)
- [Node Onboarding API Contract](../../nodes/node-onboarding-api-contract.md)

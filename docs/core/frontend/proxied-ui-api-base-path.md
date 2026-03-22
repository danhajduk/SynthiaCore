# Proxied UI API Base-Path Requirements

Status: Implemented (contract definition)
Last updated: 2026-03-22

## Purpose

Defines how browser-based node and addon UIs must address their backend APIs when running behind the Core reverse proxy.

This contract exists so proxied browser sessions never need direct access to node or addon private addresses.

## Canonical Browser API Bases

Node UI browser API base:

- `/api/nodes/{node_id}/`

Addon UI browser API base:

- `/api/addons/{addon_id}/`

Browser-origin API traffic from proxied UIs must stay on the Core public origin and use those public API bases.

## Required Behavior

- frontend code must not call the internal `ui_base_url` directly
- frontend code must not embed LAN IPs, `localhost`, or other private upstream origins into browser fetch/XHR logic
- browser API calls must derive or receive the public API base path at runtime
- all browser API requests must target the Core public origin

## Runtime Config Guidance

Recommended runtime config fields for proxied UIs:

- `public_ui_base_path`
- `public_api_base_path`
- `websocket_base_path`
- `node_id` or `addon_id`

Preferred behavior:

- derive API calls from `public_api_base_path`
- avoid baking per-node or per-addon API paths into static bundles
- allow the same UI build to work for multiple mounted instances when practical

## Rules

- browser code must never expose internal upstream addresses as its API base
- API base-path logic must tolerate changing `node_id` or `addon_id`
- browser network traffic must remain entirely on the Core public origin
- any fallback API-path derivation from `window.location` must still resolve to the canonical Core public API mount

## Implementation Patterns

### Recommended

- runtime config provides `public_api_base_path`
- API client joins request paths relative to that base
- node/addon identifier is injected by runtime context instead of hardcoded into source

### Acceptable Fallback

- frontend derives the API base from the current mounted location in a prefix-aware way
- derived path still resolves to `/api/nodes/{node_id}/` or `/api/addons/{addon_id}/`

### Not Allowed

- `fetch("http://10.0.0.5:8765/api/...")`
- `fetch("http://localhost:9000/...")`
- using `ui_base_url` as the browser API base
- hardcoding one node or addon path into a build intended for multiple mounted instances

## Acceptance Checks

A proxied UI satisfies the API base-path contract only if:

- proxied browser sessions never call internal addresses
- browser network traffic stays on the Core public origin
- API calls remain functional when `node_id` or `addon_id` changes
- the UI still works when mounted through the canonical Core proxy routes

## Failure Examples

Common API base-path failures:

- browser calls going directly to `http://127.0.0.1:...` or a LAN host
- bundles containing one fixed node id or addon id for every deployment
- API requests resolving relative to `/` instead of `/api/nodes/{node_id}/` or `/api/addons/{addon_id}/`
- mixed-origin browser requests that require CORS workarounds

## See Also

- [Proxied UI Contract](./proxied-ui-contract.md)
- [Proxied UI Path-Prefix Requirements](./proxied-ui-path-prefix.md)
- [Proxied UI Metadata](../api/proxied-ui-metadata.md)

# Proxied UI Runtime Config Contract

Status: Implemented (contract definition)
Last updated: 2026-03-22

## Purpose

Defines the runtime configuration shape and delivery strategies that proxied node and addon UIs should use instead of hardcoded build-time public paths.

This contract exists so the same UI build can be mounted behind different Core-owned paths without rebuilding per node or addon instance.

## Recommended Runtime Config Fields

- `publicOrigin`
- `publicUiBasePath`
- `publicApiBasePath`
- `websocketBasePath`
- `uiMountKind` with values `node` or `addon`
- `mountId`

## Field Meanings

- `publicOrigin`: the public browser origin for the current Core deployment
- `publicUiBasePath`: the current mounted UI base path, such as `/nodes/{node_id}/ui/` or `/addons/{addon_id}/`
- `publicApiBasePath`: the matching browser API base path, such as `/api/nodes/{node_id}/` or `/api/addons/{addon_id}/`
- `websocketBasePath`: the public websocket-compatible path root when websocket features are present
- `uiMountKind`: whether the mounted UI is a node or addon surface
- `mountId`: the current `node_id` or `addon_id`

## Delivery Options

Supported delivery strategies:

- inline JSON config in the HTML shell
- a dedicated config endpoint under the proxied public path
- server-rendered template injection

## Rules

- runtime config must be derived from the public Core route
- runtime config must not expose internal URLs or secrets
- runtime config should be preferred over hardcoded build-time paths when `node_id` or `addon_id` is dynamic
- browser clients must treat runtime config as the source of truth for public UI/API/websocket paths

## Recommended Usage Pattern

- initialize routing from `publicUiBasePath`
- initialize browser API clients from `publicApiBasePath`
- initialize websocket URLs from `publicOrigin` plus `websocketBasePath`
- treat `mountId` as runtime state, not a compiled constant

## Acceptance Checks

A proxied UI satisfies the runtime config contract only if:

- the frontend can boot correctly without knowing its `node_id` or `addon_id` at build time
- the same UI build can be reused for multiple mounted instances where appropriate
- no internal addresses leak to browser-visible config

## Failure Examples

Common runtime-config failures:

- one bundle compiled with a fixed `node_id` for every deployment
- exposing `ui_base_url` or private LAN origins in the browser config object
- deriving API and websocket paths from stale build-time constants instead of current runtime mount data

## See Also

- [Proxied UI Contract](./proxied-ui-contract.md)
- [Proxied UI API Base-Path Requirements](./proxied-ui-api-base-path.md)
- [Proxied UI Websocket Compatibility Requirements](./proxied-ui-websocket-compatibility.md)

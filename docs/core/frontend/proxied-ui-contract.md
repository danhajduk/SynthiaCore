# Proxied UI Contract

Status: Implemented (baseline contract)
Last updated: 2026-03-22

## Purpose

Defines the runtime and frontend contract for any node UI or addon UI that is mounted behind Hexe Core's reverse proxy.

This contract exists so externally hosted UIs can be embedded and operated through Core without requiring the browser to talk directly to node or addon private addresses.

## Canonical Public Mounts

Core-owned public UI mounts:

- nodes: `/nodes/{node_id}/ui/`
- addons: `/addons/{addon_id}/`

Core-owned public API mounts used by browser code:

- nodes: `/api/nodes/{node_id}/`
- addons: `/api/addons/{addon_id}/`

Legacy `/ui/nodes/...` and `/ui/addons/...` paths remain compatibility redirects only. New UI implementations must treat the canonical mounts above as authoritative.

## Core Proxy Guarantees

When a UI is proxied through Core:

- the browser talks only to the Core public origin
- Core forwards UI requests to the node or addon upstream target
- Core forwards API requests through the matching public API proxy path
- Core may forward websocket upgrades on the same public prefix
- Core rewrites root-relative HTML, JS, and CSS asset references through the active public prefix
- Core may return an operator-readable HTML fallback shell when the upstream UI is unavailable

## Required UI Behavior

Any proxied node or addon UI must follow these rules:

- it must not assume it is hosted at `/`
- it must not require direct browser access to the internal upstream URL
- it must not hardcode LAN IPs, localhost origins, or private hostnames into browser-visible links or fetch targets
- it must resolve assets, links, redirects, and navigation correctly when mounted under a non-root prefix
- browser-side API calls must use the Core public API proxy path, not the internal upstream base URL
- websocket connections must use the Core public origin and the proxied public path

## Frontend Requirements

### Routing

- SPA routers must support a configurable basename or base path
- server-rendered UIs must support a configurable root path or forwarded prefix
- deep links must load correctly from the canonical proxied public path
- refresh on a nested proxied route must keep working without escaping the prefix

### Assets

- prefer relative asset URLs where practical
- avoid hardcoded absolute asset paths that start from `/` unless the UI knows they will stay under the active public prefix
- fonts, images, stylesheets, and JS chunks must remain loadable from the canonical public mount

### Browser API Usage

- derive or receive the public API base path at runtime
- keep browser traffic on the Core public origin
- do not call `ui_base_url` or any other internal upstream address from browser code

### Websockets

- websocket URLs must preserve the mounted public prefix
- websocket clients must tolerate proxy-mediated disconnects and reconnect through the public path

## Runtime Requirements

- the upstream UI must be reachable by Core over an internal `http://` or `https://` URL
- the upstream service must tolerate being mounted below a Core-owned public prefix
- if the UI exposes health metadata, unhealthy targets may be blocked before the request is forwarded
- if the UI serves both frontend and backend behavior, the browser-visible frontend must still use the Core public API path contract

## Compatibility Checklist

Use this checklist when authoring or reviewing a node/addon UI:

- UI loads correctly from `/nodes/{node_id}/ui/` or `/addons/{addon_id}/`
- assets load without broken root-path requests
- browser refresh on a deep-linked route stays inside the proxied prefix
- in-app navigation preserves the mounted prefix
- browser API traffic stays under `/api/nodes/{node_id}/...` or `/api/addons/{addon_id}/...`
- no browser request targets the upstream private address directly
- websocket features reconnect through the proxied public path
- failure states remain understandable when Core serves a fallback error shell

## See Also

- [Frontend and UI](./frontend-and-ui.md)
- [Proxied UI Path-Prefix Requirements](./proxied-ui-path-prefix.md)
- [Proxied UI API Base-Path Requirements](./proxied-ui-api-base-path.md)
- [Proxied UI Metadata](../api/proxied-ui-metadata.md)
- [API Reference](../api/api-reference.md)
- [Addon Platform](../../addons/addon-platform.md)
- [Node Onboarding API Contract](../../nodes/node-onboarding-api-contract.md)

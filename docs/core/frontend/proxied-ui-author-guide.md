# Proxied UI Author Guide

Status: Implemented (author guide)
Last updated: 2026-03-22

## Purpose

Guidance for node and addon authors building UIs that must work behind the Hexe Core reverse proxy.

## Public Route Model

Canonical public UI mounts:

- nodes: `/nodes/{node_id}/ui/`
- addons: `/addons/{addon_id}/`

Canonical browser API mounts:

- nodes: `/api/nodes/{node_id}/`
- addons: `/api/addons/{addon_id}/`

## Core Rules

- do not assume the UI is mounted at `/`
- do not call private upstream addresses from browser code
- keep browser traffic on the Core public origin
- preserve the mounted prefix for routes, assets, redirects, and websockets

## Runtime Config Example

Recommended runtime config shape:

```json
{
  "publicOrigin": "https://feedfacecafebeef.hexe-ai.com",
  "publicUiBasePath": "/nodes/node-123/ui/",
  "publicApiBasePath": "/api/nodes/node-123/",
  "websocketBasePath": "/nodes/node-123/ui/ws",
  "uiMountKind": "node",
  "mountId": "node-123"
}
```

## Example Usage Pattern

Browser code should:

- initialize routing from `publicUiBasePath`
- initialize browser API clients from `publicApiBasePath`
- initialize websocket URLs from `publicOrigin` plus `websocketBasePath`

## Forwarded Headers

Core forwards these headers to proxied targets:

- `X-Forwarded-Host`
- `X-Forwarded-Proto`
- `X-Forwarded-Prefix`
- `X-Hexe-Node-Id` or `X-Hexe-Addon-Id` when applicable

Use them for prefix-aware link generation and redirects when your server needs absolute public URL context.

## Common Failure Cases

- assets loading from `/assets/...`
- API calls going to `localhost` or a LAN IP
- redirects escaping the mounted prefix
- websocket hosts hardcoded to internal addresses
- SPA routers not configured with a basename
- server-rendered links/forms ignoring the forwarded prefix

## Compatibility Checklist

- UI loads correctly from the canonical proxied UI route
- deep links and browser refresh work under the mounted prefix
- browser API traffic stays under the canonical Core API route
- websocket features stay on the Core public origin
- no internal addresses leak into browser-visible config, links, or redirects

## Reference Docs

- [Proxied UI Contract](./proxied-ui-contract.md)
- [Proxied UI Path-Prefix Requirements](./proxied-ui-path-prefix.md)
- [Proxied UI API Base-Path Requirements](./proxied-ui-api-base-path.md)
- [Proxied UI Websocket Compatibility Requirements](./proxied-ui-websocket-compatibility.md)
- [Proxied UI Runtime Config Contract](./proxied-ui-runtime-config.md)
- [Proxied UI Redirect And Link-Generation Contract](./proxied-ui-redirects.md)
- [Proxied UI SPA Compatibility Requirements](./proxied-ui-spa-compatibility.md)
- [Proxied UI Server-Rendered Compatibility Requirements](./proxied-ui-server-rendered-compatibility.md)
- [Proxied UI Forwarded-Header Contract](../api/proxied-ui-forwarded-headers.md)

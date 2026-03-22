# Proxied UI Websocket Compatibility Requirements

Status: Implemented (contract definition)
Last updated: 2026-03-22

## Purpose

Defines how websocket-dependent node and addon UIs must behave when mounted behind the Core reverse proxy.

This contract exists so realtime UI features continue working through the Core public origin instead of opening direct browser connections to internal node or addon addresses.

## Required Behavior

- websocket URLs must be derived from the Core public origin
- websocket paths must remain under the mounted public UI prefix or the matching public API prefix
- frontend code must not hardcode `ws://10.x.x.x`, `ws://localhost`, or other private websocket origins
- frontend code must support secure websocket usage when Core is exposed via HTTPS

## Rules

- prefer deriving the websocket endpoint from `window.location`
- prefer path-based websocket URLs rather than fixed hostnames
- websocket routing must preserve the mounted proxy prefix
- public HTTPS deployments must upgrade websocket clients to `wss://`

## Public Path Guidance

When a UI is proxied through Core, websocket paths should stay within the same public routing model:

- node UI mounts: `/nodes/{node_id}/ui/...`
- addon UI mounts: `/addons/{addon_id}/...`
- public API websocket paths, when used, should stay under `/api/nodes/{node_id}/...` or `/api/addons/{addon_id}/...`

## Compatibility Patterns

### Recommended

- build websocket URLs from the current browser origin
- join websocket paths relative to the current public UI or API base
- reconnect through the same public route after disconnects

### Not Allowed

- hardcoded internal websocket hosts in frontend bundles
- browser websocket connections that bypass Core and talk directly to upstream private addresses
- `ws://` usage on a public HTTPS deployment

## Acceptance Checks

A proxied UI satisfies the websocket compatibility contract only if:

- websocket UI features work through the Core proxy
- no direct browser websocket connection to internal targets exists
- public HTTPS deployment upgrades correctly to `wss://`
- websocket reconnect behavior stays on the Core public origin

## Failure Examples

Common websocket compatibility failures:

- a bundle containing `ws://localhost:3000/socket`
- reconnect logic dropping the `/nodes/{node_id}/ui/` or `/addons/{addon_id}/` prefix
- browser console errors caused by mixed-content websocket connections under HTTPS

## See Also

- [Proxied UI Contract](./proxied-ui-contract.md)
- [Proxied UI Path-Prefix Requirements](./proxied-ui-path-prefix.md)
- [Proxied UI API Base-Path Requirements](./proxied-ui-api-base-path.md)

# Proxied UI Forwarded-Header Contract

Status: Implemented (baseline headers)
Last updated: 2026-03-22

## Purpose

Defines the request headers Hexe Core forwards to node and addon UI/API targets so downstream applications can understand their public mounting context.

## Required Forwarded Headers

Core sets these headers consistently for proxied HTTP and websocket traffic:

- `X-Forwarded-Host`
- `X-Forwarded-Proto`
- `X-Forwarded-Prefix`

Current meanings:

- `X-Forwarded-Host`: the public host seen by the browser when the request reached Core
- `X-Forwarded-Proto`: the browser-visible request scheme at Core, such as `http` or `https`
- `X-Forwarded-Prefix`: the public mount prefix owned by Core for that proxied surface

## Contextual Identity Headers

Core also injects target identity headers when applicable:

- `X-Hexe-Node-Id`
- `X-Hexe-Addon-Id`

Current behavior:

- node proxy routes include `X-Hexe-Node-Id`
- addon proxy routes include `X-Hexe-Addon-Id`
- these headers let downstream apps associate the request with the mounted Core target identity

## Request-ID Note

Planned contract language may mention `X-Request-Id`, but the current proxy implementation does not inject it universally yet.

Downstream applications must not depend on `X-Request-Id` being present until Core explicitly standardizes and emits it.

## Rules For Downstream Targets

- targets may use `X-Forwarded-Prefix` to construct links, redirects, and routing behavior that stay under the correct public mount
- targets may use `X-Forwarded-Host` and `X-Forwarded-Proto` to reconstruct public absolute URLs when relative URLs are not sufficient
- targets must not trust arbitrary client-supplied values for these headers unless they are known to come from Core
- targets should treat these headers as Core-owned context rather than end-user input

## Consistency Rules

- forwarded headers should be interpreted the same way for both proxied UI and proxied API traffic
- websocket-capable targets should apply the same prefix/host/proto interpretation to upgraded connections
- downstream applications should prefer `X-Forwarded-Prefix` over guesswork from internal upstream paths

## Acceptance Checks

A proxied target satisfies the forwarded-header contract only if:

- it can determine its public mount path from `X-Forwarded-Prefix`
- it can reconstruct public absolute URLs safely from forwarded host/proto when needed
- it does not generate links or redirects that escape the Core public mount

## See Also

- [Proxied UI Contract](../frontend/proxied-ui-contract.md)
- [Proxied UI Path-Prefix Requirements](../frontend/proxied-ui-path-prefix.md)
- [Proxied UI Websocket Compatibility Requirements](../frontend/proxied-ui-websocket-compatibility.md)

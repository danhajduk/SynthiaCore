# Proxied UI Server-Rendered Compatibility Requirements

Status: Implemented (contract definition)
Last updated: 2026-03-22

## Purpose

Defines explicit compatibility requirements for server-rendered proxied UIs such as FastAPI, Flask, Django, or similar applications mounted behind Core.

## Required Capabilities

- support a configurable root path or forwarded prefix
- generate links and redirects relative to the mounted public prefix
- serve assets relative to the mounted public prefix
- support websocket path derivation when websocket features are present

## Recommended Patterns

- honor forwarded prefix headers
- honor forwarded proto and host when absolute URLs are necessary
- use application `root_path` or framework equivalent when supported
- avoid absolute internal URL generation

## Rules

- server-rendered responses must not leak internal upstream hostnames
- server-generated links and forms must remain valid under `/nodes/{node_id}/ui/` or `/addons/{addon_id}/`
- redirect responses must preserve the proxied Core route
- asset responses must stay compatible with the mounted public prefix

## Acceptance Checks

A proxied server-rendered UI satisfies the compatibility contract only if:

- the UI works under the mounted public prefix
- redirects and links remain correct
- no internal URLs leak into responses

## Failure Examples

Common server-rendered compatibility failures:

- `url_for` or equivalent generating `/login` instead of `/nodes/{node_id}/ui/login`
- templates emitting `http://127.0.0.1:...` absolute links
- assets referenced from `/static/...` without a prefix-aware root-path strategy

## See Also

- [Proxied UI Contract](./proxied-ui-contract.md)
- [Proxied UI Path-Prefix Requirements](./proxied-ui-path-prefix.md)
- [Proxied UI Redirect And Link-Generation Contract](./proxied-ui-redirects.md)
- [Proxied UI Forwarded-Header Contract](../api/proxied-ui-forwarded-headers.md)

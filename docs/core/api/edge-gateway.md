# Edge Gateway

Status: Implemented for Phase 5 V1 single-owner auto-provisioning

## Overview

The Hexe Core Edge Gateway makes Core the public ingress point for the platform.

Request path:

- Client -> Cloudflare Tunnel -> Core public UI hostname
- Client -> Cloudflare Tunnel -> Core public API hostname
- Core -> local UI/API services
- Core -> Supervisor-managed runtimes
- Core -> trusted nodes through explicit later publications

## Core-ID Hostname Model

Each Core instance owns a stable persisted `core_id`.

Canonical hostnames:

- UI: `<core-id>.hexe-ai.com`
- API: `api.<core-id>.hexe-ai.com`

Rules:

- `core_id` is generated once and persisted in Core settings
- default format is 16-character lowercase hex
- hostnames are derived deterministically from `core_id`
- hostname is addressability only, not the trust mechanism

Trust still relies on stored credentials, trust tokens, governance, and service/node policy.

## Responsibilities

Core:

- owns the canonical public identity
- validates and stores publication records
- derives Core-owned UI/API hostnames
- stores Cloudflare owner/account/zone/token-reference settings
- provisions or repairs the managed tunnel and DNS state
- renders desired Cloudflare tunnel ingress config
- exposes edge status, dry-run validation, live provision, and reconcile APIs

Supervisor:

- owns host-local `cloudflared` runtime state
- stores rendered runtime config on disk with the live tunnel token redacted
- realizes the connector process locally, using Docker by default in V1
- reports real runtime status back to Core instead of a config-only placeholder
- does not perform multi-tenant Cloudflare selection in V1

Nodes:

- are not directly public by default
- can only be published through validated Core-managed publications
- must remain trusted before node-target publications are allowed

## Publication Model

Built-in Core-owned publications always exist logically:

- `core-ui` -> `http://127.0.0.1:80`
- `core-api` -> `http://127.0.0.1:9001`

Additional publications are operator-defined and constrained to the platform-owned base domain.

Validated publication rules include:

- hostname must stay under `hexe-ai.com`
- Core-owned hostnames cannot be spoofed
- duplicate hostname/path combinations are rejected
- node targets must still be trusted
- supervisor runtime targets must exist
- upstream forwarding is allow-listed to local loopback targets in V1

## Security Boundaries

- Core remains the policy and publication authority
- Supervisor remains the host-local runtime authority
- edge proxy forwarding uses SSRF guards, header filtering, and bounded timeouts
- Cloudflare ownership is single-owner and platform-managed in V1
- Core-derived UI/API hostnames cannot be replaced by operator-defined publications

## Cloudflare Provisioning

V1 uses a deterministic managed tunnel name:

- `hexe-core-<core-id>`

Live provisioning flow:

1. validate settings and token reference
2. ensure the stable `core_id` and hostnames exist
3. find or create the deterministic tunnel
4. push the canonical ingress configuration to Cloudflare through the tunnel configurations API
5. upsert DNS for:
   - `<core-id>.hexe-ai.com`
   - `api.<core-id>.hexe-ai.com`
6. resolve the live tunnel token in-memory
7. hand runtime config to Supervisor
8. persist provisioning status and resource ids

Settings notes:

- the account source is fixed to `env:CLOUDFLARE_ACCOUNT_ID`
- the zone source is fixed to `env:CLOUDFLARE_ZONE_ID`
- the token source is fixed to `env:CLOUDFLARE_API_TOKEN`
- Core stores the fixed env-backed token reference, not the raw token
- only `hexe-ai.com` is allowed as the managed base in V1
- changing the Cloudflare owner context clears stale persisted remote ids so reprovisioning is clean

Runtime notes:

- Supervisor defaults to `SYNTHIA_CLOUDFLARED_PROVIDER=auto`
- `auto` prefers Docker and falls back to a native `cloudflared` binary if available
- tests and non-runtime environments can set `SYNTHIA_CLOUDFLARED_PROVIDER=disabled`
- the Docker runtime uses host networking so the tunnel can reach Core services at `127.0.0.1`

## Status And Observability

`GET /api/edge/status` exposes:

- public UI/API hostnames
- Cloudflare settings projection
- tunnel/configured runtime state
- provisioning state projection
- publication list
- validation errors
- reconcile outcome
- real connector runtime state from Supervisor

`GET /api/edge/cloudflare` exposes the Cloudflare-focused status slice:

- settings projection
- tunnel/runtime state
- provisioning state
- reconcile state
- validation errors

Edge changes emit audit events for:

- Cloudflare settings updates
- dry-run attempts
- provision attempts
- publication create/update/delete
- tunnel creation
- DNS reconciliation
- Supervisor runtime apply
- reconcile completion

## Cloudflare Ownership Model

Phase 4 intentionally supports only:

- one Cloudflare owner
- one Cloudflare account context
- one Cloudflare zone context
- one managed base domain: `hexe-ai.com`

Out of scope for V1:

- bring-your-own-domain
- per-tenant Cloudflare accounts
- user-owned zones
- multi-owner selection logic

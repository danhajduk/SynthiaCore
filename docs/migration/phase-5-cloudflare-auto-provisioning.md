# Phase 5 Cloudflare Auto-Provisioning

Status: Implemented for V1 single-owner platform-managed provisioning

## Purpose

Phase 5 extends the Phase 4 edge gateway foundation so Hexe Core can provision and reconcile its public Cloudflare tunnel and DNS state automatically.

This removes the earlier manual tunnel-id-first workflow and replaces it with a Core-owned desired-state model.

## Scope

Phase 5 covers:

- persisted Cloudflare account, zone, and token-reference settings
- deterministic tunnel naming derived from the stable `core_id`
- tunnel lookup or creation through the Cloudflare API
- DNS reconciliation for the canonical UI and API hostnames
- tunnel configuration reconciliation through the Cloudflare configurations API
- persisted provisioning state and operator-visible status
- rendered `cloudflared` runtime config handoff to Supervisor
- dry-run validation and live provision actions from API and UI

## Relationship To Phase 4

Phase 4 introduced:

- the stable persisted `core_id`
- the public hostname model
- the edge gateway store, service, router, and UI
- the Supervisor handoff adapter for `cloudflared`

Phase 5 keeps those contracts and adds Cloudflare ownership automation on top of them.

## V1 Ownership Model

V1 remains intentionally platform-managed only:

- one Cloudflare owner
- one Cloudflare account context
- one Cloudflare zone context
- one managed base domain: `hexe-ai.com`
- one platform-managed API token source

Out of scope:

- bring-your-own Cloudflare account
- bring-your-own domain
- tenant-specific token selection
- user-facing Cloudflare OAuth

## Lifecycle

1. Core loads the stable `core_id`.
2. Core derives:
   - `<core-id>.hexe-ai.com`
   - `api.<core-id>.hexe-ai.com`
3. Operator saves Cloudflare settings with:
   - fixed account source: `env:CLOUDFLARE_ACCOUNT_ID`
   - fixed zone source: `env:CLOUDFLARE_ZONE_ID`
   - `managed_domain_base`
   - fixed token source: `env:CLOUDFLARE_API_TOKEN`
4. Dry-run validation confirms the config is structurally usable.
5. Live provisioning:
   - resolves the token reference from the environment
   - looks up an existing deterministic tunnel
   - creates the tunnel if missing
   - pushes the canonical ingress configuration to Cloudflare
   - fetches the live tunnel token
   - upserts the UI and API DNS records
   - renders the `cloudflared` runtime config
   - hands desired runtime config to Supervisor
6. Core persists the provisioned tunnel and DNS metadata and exposes the result through edge status APIs.

## Tunnel Naming

The canonical V1 tunnel name is:

- `hexe-core-<core-id>`

Rules:

- lowercase ASCII only
- deterministic for the life of the Core instance
- tied directly to the persisted `core_id`
- used as the lookup key before creating a new tunnel

## Idempotency And Recovery

Provisioning must be safe to retry.

Implemented behavior:

- tunnel lookup uses persisted `tunnel_id` first, then the deterministic tunnel name
- repeated provision calls reuse the same tunnel when it still exists
- DNS reconciliation is name-based and updates stale content in place
- changing the Cloudflare owner context clears persisted tunnel and DNS metadata so Core can reprovision cleanly
- reconcile and provision both reuse the same provisioning flow

## Security Notes

- the UI never returns a raw Cloudflare API token
- Core uses the fixed env-backed account source `env:CLOUDFLARE_ACCOUNT_ID`
- Core uses the fixed env-backed zone source `env:CLOUDFLARE_ZONE_ID`
- Core uses the fixed env-backed token source `env:CLOUDFLARE_API_TOKEN`
- live token resolution uses environment-backed references
- provisioning and settings mutation remain admin-only actions
- logs and audit events record metadata and outcomes, not the raw token

## Supervisor Handoff

Core hands Supervisor a rendered desired config that includes:

- tunnel id
- canonical ingress config
- managed domain base
- live tunnel token in-memory for the apply call only
- desired enabled state
- provisioning state

Supervisor remains responsible for host-local `cloudflared` runtime realization and runtime-state reporting.

Implemented V1 runtime behavior:

- Supervisor defaults to `SYNTHIA_CLOUDFLARED_PROVIDER=auto`
- `auto` prefers a Docker-managed `cloudflare/cloudflared:latest` connector
- Docker launches with host networking so remote ingress rules can target `127.0.0.1:80` and `127.0.0.1:9001`
- a native `cloudflared` binary is used only if Docker is unavailable
- the persisted on-disk config redacts the live tunnel token

## Rollback And Reprovision

If provisioning state becomes stale or invalid:

- operators can correct the account, zone, or token reference
- Core clears stale persisted Cloudflare metadata when the owner context changes
- operators can rerun provision or reconcile safely

If remote Cloudflare objects disappear:

- Core reuses the deterministic tunnel name and DNS hostnames to repair state on the next live provision

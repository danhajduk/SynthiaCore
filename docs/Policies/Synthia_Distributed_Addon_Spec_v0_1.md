# Synthia Distributed Addon Spec v0.1 (General)
Version: 0.1  
Date: 2026-02-28

This document defines a **general, reusable** structure for running Synthia addons as **independent services** that can live on the same host as Core or on different machines, while Core remains a **control plane** (registry/auth/policy/UI/proxy), not a data-path broker.

> Design goals
- **Non-interference**: addons keep running if Core is down; Core must not be required for realtime ingestion/processing.
- **Distributed by default**: any addon may run remotely.
- **Unified operator UX**: Core provides consistent auth/UI and a reverse-proxy path.
- **Shared services**: some addons provide services (AI, Gmail, Storage). Others consume them with scoped tokens and quota grants.

---

## 1) Actors and Planes

### Control plane (Synthia Core)
Core provides:
- Addon registry (what exists, where, capabilities)
- Authentication and authorization authority
- Token issuer (service tokens)
- Policy/quota authority (grants + revocations)
- Reverse proxy for UI/API (browser → core → addon)
- Global settings and per-addon config management
- Telemetry aggregation and dashboards

Core does **not**:
- Relay high-frequency events (camera frames, sensor streams)
- Perform service work on behalf of addons (unless explicitly configured)
- Become a single point of failure for data-path operations

### Data plane (Addons)
Each addon is an independent service that may:
- Ingest data directly (MQTT, webhooks, polling)
- Store local runtime state (DB/files)
- Publish results to MQTT/HA
- Provide a service interface to other addons (e.g., AI, Gmail)

---

## 2) Addon Types

### A) Standalone feature addon
Provides UI + API for a feature domain (e.g., Vision).  
May ingest its own signals and publish results.

### B) Service addon
Provides a shared capability to other addons (e.g., AI, Gmail, Storage).
- Must publish its **service catalog** (capabilities + limits)
- Must enforce **quota grants** and **permission scopes**
- Must report usage back to Core

### C) Bridge addon (optional)
Connects external systems to Synthia’s internal standards (e.g., webhook ingress, protocol gateways).
Should remain thin.

---

## 3) Filesystem Structure (Monorepo-friendly)
A general addon folder layout (same whether local or remote):

```
addons/<addon_id>/
  manifest.json
  backend/
    addon.py          # exports meta + router (local-core embedding)
    router.py         # route definitions
    services/         # domain logic
    models/           # pydantic models
  frontend/
    index.ts
    routes.tsx
    pages/
  worker/             # long-running loops (optional)
    run.py
  runtime/            # local state (gitignored)
    data/
    logs/
```

Notes:
- **runtime/** is owned by the addon and is local to where it runs.
- When an addon runs remotely, the directory layout is conceptually the same, but Core only interacts via network.

---

## 4) Addon Identity & Metadata

### 4.1 Addon meta endpoint (required)
`GET /api/addon/meta` returns:

- `id`, `name`, `version`
- `base_url` (optional; Core can override)
- `capabilities`: list of capability strings
- `ui`: `{ enabled: bool, base_path: str }`
- `auth`: `{ required: bool, modes: [...] }`
- `limits` (optional): service capacity declarations (for service addons)

### 4.2 Capability naming
Format: `<domain>.<action>[.<subaction>]`

Examples:
- `vision.ingest`
- `vision.journal.read`
- `ai.classify`
- `ai.embed`
- `gmail.send`
- `storage.object.write`

Capabilities are used for:
- Service discovery
- Permission scopes
- Quota assignment
- UI feature gating

---

## 5) Core Registry & Reverse Proxy

### 5.1 Registry record (Core-side)
Core stores for each addon:
- `id`, `name`, `version`
- `base_url`
- `capabilities`
- `health_status`, `last_seen`
- `auth_mode` and required credentials (stored securely)

### 5.2 Reverse proxy (recommended)
Core exposes stable internal paths:
- `GET/POST /api/addons/<id>/*` → proxied to remote addon API
- `GET /addons/<id>/*` → UI routes inside Core shell (preferred)
- Addon may still offer its own standalone UI at `/ui` for break-glass access.

Why proxy:
- browser talks to **one origin**
- Core retains control of auth, rate limits, and audit logs

---

## 6) MQTT Broker Options (Core Install)

Core supports two configurations:

### Option A: Local broker addon (default “works everywhere”)
- Core starts an MQTT broker locally (container/service).
- Persistent storage enabled.
- Broker health monitored by Core.

### Option B: External broker
- User provides `host:port` + credentials at install.
- Core validates connection (TCP + MQTT handshake).
- Core stores settings securely.

> Recommendation: keep install deterministic (no “mystery scanning”).
Optionally provide “Try common defaults” + “Test connection”.

---

## 7) Discovery and Announce Protocol

Discovery can be MQTT-first once a broker exists.

### 7.1 Addon announce (retained)
Topic: `synthia/addons/<id>/announce` (retained)  
Payload includes:
- id, version, base_url
- capabilities
- last_seen
- optional: runtime host hints (hostname, ip)

### 7.2 Health (retained + periodic update)
Topic: `synthia/addons/<id>/health` (retained)  
Payload:
- status: `healthy|degraded|offline`
- last_seen
- brief reason codes (no secrets)

### 7.3 Service catalog (service addons)
Topic: `synthia/services/<service_id>/catalog` (retained)  
Payload:
- provided capabilities
- declared max daily capacity (tokens/cents/requests)
- SLA hints (timeouts, concurrency)

Core may also accept **phone-home registration** as a secondary mechanism for WAN setups:
- addon is configured with `CORE_URL` and a pairing secret
- addon registers itself to core on startup

---

## 8) Standard HTTP Endpoints (Minimum Set)

All addons MUST implement:
- `GET  /api/addon/meta`
- `GET  /api/addon/health`
- `GET  /api/addon/config/effective` (admin)
- `POST /api/addon/config` (admin; validated)
- `GET  /api/addon/capabilities`

Optional but strongly recommended:
- `POST /api/addon/control/<action>` (pause/resume/reload)
- `GET  /api/addon/telemetry` (local view)

Service addons additionally implement:
- `GET  /api/service/catalog`
- `POST /api/service/request` (or domain-specific endpoints)
- `POST /api/service/usage/report` (to core) OR core pull model

---

## 9) Tokens, Permissions, and Quotas (General)

### 9.1 Service token (JWT)
Core issues short-lived JWTs containing:
- `sub`: calling addon id
- `aud`: target service addon id (or service name)
- `scp`: scopes (capabilities permitted)
- `exp`: expiry
- `jti`: token id

Tokens are used for addon→addon calls (direct), without Core in the request path.

### 9.2 Quota grants (policy vs enforcement)
Core is **policy authority** (assigns grants).  
Service addon is **enforcement point** (enforces per request).

A grant is keyed by: `(consumer_addon, service, period)` and includes:
- `grant_id`
- `consumer_addon_id`
- `service`
- `period_start`, `period_end`
- limits: one or more of:
  - `max_requests`
  - `max_tokens`
  - `max_cost_cents`
- status: `active|revoked|expired`

### 9.3 Usage reporting
Service addon reports periodically to Core:
- usage by consumer and service
- denials by reason (quota, auth, rate limit)
- latency/health metrics (optional)

### 9.4 Revocation
Core may revoke:
- tokens (by `jti`)
- grants (by `grant_id`)

Distribution:
- MQTT retained revocation lists, plus
- periodic polling fallback by service addon

### 9.5 Examples beyond AI
- Gmail service addon:
  - declares max daily send budget (count + provider limits)
  - Core assigns daily send grants per consumer addon
- Storage service addon:
  - declares max daily write bytes or API calls
  - Core assigns per consumer addon limits

---

## 10) Non-Interference Rules (Hard Requirements)

- Addon must degrade gracefully when Core is unreachable.
- Service addon must enforce quotas locally without requiring Core in the hot path.
- Core must not “break” addons by restarting them or changing state unexpectedly.
- Control actions must be explicit and authenticated.
- Avoid secret propagation over MQTT; use HTTP + secure storage for secrets.

---

## 11) Observability (Recommended Baseline)

### Telemetry categories
- health: uptime, status, last_seen
- capacity: concurrency, queue depth
- usage: cost/tokens/requests
- performance: latency p50/p95, error rates

### Minimum MQTT telemetry
- announce
- health
- policy grants + revocations (retained)

---

## 12) Security Baseline

- TLS required for remote (non-localhost) traffic (recommended from day 1 for WAN)
- Service tokens are short-lived + scoped (least privilege)
- Secrets are stored only in Core secure store and service addon secure store
- Rate limits per addon per service
- Audit logs for: grant changes, revocations, privileged config updates

---

## 13) Phased Implementation Plan (Suggested)

1) Core registry + proxy (browser→core→addon)
2) Addon meta/health endpoints and MQTT announce/health
3) Policy grants + revocation channels (MQTT retained)
4) Service token issuance (JWT)
5) Service addon quota enforcement + usage reporting
6) Optional: supervisor/worker orchestration

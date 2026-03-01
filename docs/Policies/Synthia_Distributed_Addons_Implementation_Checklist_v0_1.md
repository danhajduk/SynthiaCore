# Synthia Distributed Addons — Implementation Checklist v0.1
Date: 2026-02-28  
Scope: General platform work to enable *any* addon to run locally or remotely, discoverable via MQTT, managed by Core (control plane), and able to consume shared services (AI/Gmail/etc.) with tokens + quota grants.

> Principles
- Core is **control plane**, not data plane.
- Addons must continue operating if Core is unavailable.
- Services enforce quota locally; Core issues policy and can revoke.
- MQTT is the default discovery/telemetry bus (after broker exists).

---

## Phase 0 — Baseline Foundations (Prereqs)
- [ ] Confirm Core has a secure settings store (file + encryption OR DB + secrets table).
- [ ] Confirm Core has an auth layer for admin vs guest vs service.
- [ ] Define a stable place for “system identity” (Core instance id) and key material (JWT signing keys).
- [ ] Ensure per-addon runtime directories are gitignored and writable.

Deliverable:
- `docs/distributed_addons/README.md` linking to the spec + diagrams + this checklist.

---

## Phase 1 — MQTT Bootstrap (Install-time)
### Core install UX (two options)
- [ ] **Option A (Local broker addon)**: add install toggle “Run local MQTT broker” (default on).
- [ ] **Option B (External broker)**: collect host:port + username/password; include “Test connection”.

### Core broker management
- [ ] If Option A chosen, implement MQTT addon start (container/service) with persistent volume.
- [ ] Add Core-level MQTT connection manager with health + reconnect.
- [ ] Add Core endpoints:
  - [ ] `GET /api/system/mqtt/status`
  - [ ] `POST /api/system/mqtt/test` (Option B)
  - [ ] `POST /api/system/mqtt/restart` (admin)

### MQTT minimal topics (Core-owned)
- [ ] Reserve root prefix: `synthia/`
- [ ] Define retained broker info topic (optional but helpful):
  - [ ] `synthia/core/mqtt/info` (retained): host, port, tls, last_seen (no secrets)

Acceptance tests
- [ ] With local broker enabled: Core boots and publishes `synthia/core/mqtt/info`.
- [ ] With external broker: test endpoint validates connect + CONNACK.

---

## Phase 2 — Addon Registry in Core + Reverse Proxy
### Core registry data model
- [ ] Persist registry entries:
  - id, name, version
  - base_url
  - capabilities
  - auth_mode (core_proxy_auth|passthrough)
  - last_seen, health_status
  - tags/labels (optional)
- [ ] Add CRUD endpoints (admin):
  - [ ] `GET /api/admin/addons/registry`
  - [ ] `POST /api/admin/addons/registry` (manual add/edit)
  - [ ] `DELETE /api/admin/addons/registry/{id}`

### Reverse proxy
- [ ] Implement proxy routing:
  - [ ] `/api/addons/{id}/*` → `{base_url}/api/...`
  - [ ] (optional) `/ui/addons/{id}/*` → `{base_url}/ui/...`
- [ ] Inject auth headers/tokens server-side (Core → Addon).
- [ ] Add per-addon timeouts, retry policy, and circuit breaker in proxy layer.

### UI surfaces
- [ ] Add an “Addons” admin page:
  - [ ] registry list
  - [ ] health/last_seen
  - [ ] base_url edit
  - [ ] capabilities display

Acceptance tests
- [ ] Register a dummy remote addon and successfully proxy one API call.
- [ ] Proxy never leaks addon secrets to the browser.

---

## Phase 3 — Standard Addon API Contract (All Addons)
### Required endpoints (addon side)
- [ ] `GET /api/addon/meta`
- [ ] `GET /api/addon/health`
- [ ] `GET /api/addon/capabilities`
- [ ] `GET /api/addon/config/effective` (admin)
- [ ] `POST /api/addon/config` (admin)

### Core validation
- [ ] Core validates meta schema and stores capabilities.
- [ ] Core health-check loop:
  - [ ] periodic polling via HTTP (optional)
  - [ ] MQTT-based last_seen (preferred once announce exists)

Acceptance tests
- [ ] Addon passes “contract check” tool in Core.
- [ ] Config update persists and reflected in effective config.

---

## Phase 4 — MQTT Discovery + Telemetry (Default Bus)
### Addon announce + health topics (addon side)
- [ ] Publish retained announce:
  - [ ] `synthia/addons/{id}/announce`
- [ ] Publish retained health:
  - [ ] `synthia/addons/{id}/health`
- [ ] Include fields:
  - id, version, base_url, capabilities, last_seen, status

### Core subscriptions
- [ ] Core subscribes:
  - [ ] `synthia/addons/+/announce`
  - [ ] `synthia/addons/+/health`
- [ ] Core updates registry `last_seen` and `health_status` from MQTT.

### Service catalogs (service addons)
- [ ] Service addon publishes retained:
  - [ ] `synthia/services/{service_id}/catalog`
- [ ] Core subscribes:
  - [ ] `synthia/services/+/catalog`
- [ ] Core offers service resolution endpoint:
  - [ ] `GET /api/services/resolve?capability={cap}`

Acceptance tests
- [ ] Addon appears automatically in Core registry after MQTT announce.
- [ ] Service catalog publishes and resolves via Core endpoint.

---

## Phase 5 — Tokens & Permissions (Service-to-Service)
### Core: JWT issuer
- [ ] Define JWT signing keys and rotation strategy.
- [ ] Implement token endpoint (service clients):
  - [ ] `POST /api/auth/service-token`
- [ ] Token claims:
  - sub (consumer addon id)
  - aud (service id or service addon id)
  - scp (scopes/capabilities)
  - exp (TTL)
  - jti (unique)

### Service addon: auth middleware
- [ ] Validate signature, exp, aud, scp.
- [ ] Reject missing/invalid scope.

Acceptance tests
- [ ] Consumer addon can fetch token and call service addon directly.
- [ ] Service denies calls without scope.

---

## Phase 6 — Quota Grants (General, Not AI-Specific)
### Concepts
- Service addon declares **max daily capacity** (requests/tokens/cost/bytes).
- Core assigns **grants** to consumers per service.
- Service addon enforces grants locally.
- Service addon reports usage periodically to Core.
- Core can revoke grants/tokens and notify.

### Data models
- [ ] Grant schema:
  - grant_id, consumer_addon_id, service, period_start/end
  - limits: max_requests/max_tokens/max_cost_cents/max_bytes (one or more)
  - status active|revoked|expired
- [ ] Usage report schema:
  - service, consumer_addon_id, grant_id
  - used_requests/used_tokens/used_cost/used_bytes
  - denials, error counts, latency stats (optional)

### Distribution
- [ ] Core publishes retained grants:
  - [ ] `synthia/policy/grants/{service}`
- [ ] Service addon subscribes and caches locally.

### Revocation
- [ ] Core publishes retained revocations:
  - [ ] `synthia/policy/revocations/{consumer_addon_id}`
  - [ ] `synthia/policy/revocations/{grant_id}`
- [ ] Service addon polls Core revocations as fallback (30–60s).

### Reporting
- [ ] Service addon sends periodic usage to Core (HTTP):
  - [ ] `POST /api/telemetry/usage`
- [ ] Core updates dashboards and can adjust tomorrow’s grants.

Acceptance tests
- [ ] Grant limits enforced locally even if Core is down.
- [ ] Revocation takes effect quickly (MQTT retained + poll fallback).
- [ ] Example service: Gmail (max daily send count) behaves the same as AI (tokens/cost).

---

## Phase 7 — Supervisor Layer (Optional, Later)
Goal: give Core an operator panel for worker lifecycle without making it required.

- [ ] Define optional control endpoints (addon side):
  - [ ] `POST /api/addon/control/pause`
  - [ ] `POST /api/addon/control/resume`
  - [ ] `POST /api/addon/control/reload_config`
- [ ] Add Core UI buttons to call these via proxy.
- [ ] If you later add process orchestration, keep it pluggable:
  - docker-compose manager
  - systemd
  - scheduler-managed jobs

Acceptance tests
- [ ] Pause/resume works without restarting the service.
- [ ] Reload config applies safely and idempotently.

---

## Phase 8 — Hardening + UX Polish (Recommended)
- [ ] Per-addon rate limits at Core proxy.
- [ ] Audit logs for: grants, revocations, config updates.
- [ ] TLS for remote addon links (LAN ok without TLS if you accept risk; WAN requires TLS).
- [ ] “Break-glass” direct UI link shown in Core for each addon.
- [ ] Health badges in nav + alerting when addons go offline.
- [ ] Export/import registry (backup/restore).

---

## Definition of Done (Platform v0.1)
- [ ] Core can run with local MQTT broker or external broker.
- [ ] Any addon can be remote and auto-discovered via MQTT announce.
- [ ] Core proxies browser API calls to remote addons securely.
- [ ] Service addons publish catalogs; consumers resolve providers.
- [ ] Consumers call services directly using Core-issued JWTs.
- [ ] Quotas are assigned by Core, enforced by service addons, with revocation + reporting.
- [ ] Core outage does not stop addon data-plane operation.


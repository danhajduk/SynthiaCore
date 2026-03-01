# Synthia Distributed Addons — Sequence Diagrams (General)
Version: 0.1  
Date: 2026-02-28

These diagrams use Mermaid. Paste into any Mermaid renderer (GitHub, Mermaid Live, etc.).

---

## 1) Bootstrapping MQTT (Core Install)

```mermaid
sequenceDiagram
  autonumber
  participant U as User
  participant C as Core
  participant M as MQTT Broker (local addon or external)

  U->>C: Install Core
  alt Option A: Local broker addon
    C->>M: Start broker service (local)
    C->>M: Health check + create credentials
  else Option B: External broker
    U->>C: Provide host:port + creds
    C->>M: Connect + MQTT handshake test
  end
  C->>C: Persist broker config
  C-->>U: MQTT ready
```

---

## 2) Addon Announces Itself via MQTT (Discovery)

```mermaid
sequenceDiagram
  autonumber
  participant A as Addon (remote/local)
  participant M as MQTT Broker
  participant C as Core

  A->>M: PUBLISH retained synthia/addons/<id>/announce
  A->>M: PUBLISH retained synthia/addons/<id>/health
  C->>M: SUBSCRIBE synthia/addons/+/announce
  C->>M: SUBSCRIBE synthia/addons/+/health
  M-->>C: retained announce + health
  C->>C: Update registry (base_url, capabilities, last_seen)
```

---

## 3) Browser Uses Core Proxy to Reach Remote Addon API

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser
  participant C as Core Proxy
  participant A as Addon API

  B->>C: GET /api/addons/<id>/events
  C->>A: GET <base_url>/api/events (auth injected by Core)
  A-->>C: 200 JSON
  C-->>B: 200 JSON
```

---

## 4) Service Discovery (Addon Looks Up Service Location)

```mermaid
sequenceDiagram
  autonumber
  participant V as Consumer Addon
  participant M as MQTT Broker
  participant C as Core
  participant S as Service Addon

  S->>M: PUBLISH retained synthia/services/<svc>/catalog
  C->>M: SUBSCRIBE synthia/services/+/catalog
  C->>C: Registry knows provider base_url for service
  V->>C: GET /api/services/resolve?capability=ai.classify
  C-->>V: { service_base_url, service_id, required_scopes }
```

---

## 5) Grant Distribution (Core → Service Addon)

```mermaid
sequenceDiagram
  autonumber
  participant C as Core (Policy Authority)
  participant M as MQTT Broker
  participant S as Service Addon (Enforcement)

  C->>M: PUBLISH retained synthia/policy/grants/<service>
  S->>M: SUBSCRIBE synthia/policy/grants/<service>
  M-->>S: retained grants update
```

---

## 6) Direct Service Call with Token + Quota (Consumer → Service Addon)

```mermaid
sequenceDiagram
  autonumber
  participant V as Consumer Addon
  participant S as Service Addon
  participant C as Core (Token Issuer + Ledger)

  V->>C: Request service token (scoped, TTL)
  C-->>V: JWT (scopes, exp)
  V->>S: POST /api/service/request (JWT + grant_id)
  S->>S: Validate JWT + scope
  S->>S: Check local grant balance
  alt allowed
    S->>S: Execute service
    S-->>V: 200 result + usage details
    S->>C: POST /api/telemetry/usage (periodic batch)
  else denied (quota)
    S-->>V: 429/403 quota_denied + remaining
  end
```

---

## 7) Revocation (Core → Service Addon + Consumer)

```mermaid
sequenceDiagram
  autonumber
  participant C as Core
  participant M as MQTT Broker
  participant S as Service Addon
  participant V as Consumer Addon

  C->>M: PUBLISH retained synthia/policy/revocations/<consumer_id>
  C->>M: PUBLISH retained synthia/policy/revocations/<grant_id>
  S->>M: SUBSCRIBE revocations topics
  V->>M: SUBSCRIBE its revocations topic (optional)
  M-->>S: retained revocation update
  M-->>V: retained revocation update
  S->>S: Deny future requests for revoked token/grant
  V->>V: Degrade gracefully (service_unavailable/budget_revoked)
```

---

## 8) Core Down (Non-Interference)

```mermaid
sequenceDiagram
  autonumber
  participant V as Consumer Addon
  participant S as Service Addon
  participant C as Core

  note over C: Core becomes unreachable
  V->>S: Continue direct service calls with still-valid JWT until exp
  S->>S: Enforce local grant balance
  V->>V: If token expires, degrade (no new token)
  S->>S: Queue usage reports until Core returns
```

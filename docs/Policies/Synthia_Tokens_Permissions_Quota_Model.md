# Synthia Tokens, Permissions & Quota Model

Version: 0.1\
Date: 2026-02-28

## 1. Service Tokens (JWT)

Core issues short-lived JWT tokens containing:

-   addon_id
-   scopes (service permissions)
-   audience (target service addon)
-   expiry (5 minutes -- 24 hours)
-   jti (unique token id)

Tokens are signed by Core.

------------------------------------------------------------------------

## 2. Capability Scopes

Example scopes:

-   ai.classify
-   ai.embed
-   gmail.send
-   storage.object.write

Tokens must contain only necessary scopes.

------------------------------------------------------------------------

## 3. Quota / Grant Model

Core is policy authority.\
Service addon is enforcement authority.

Each service grant includes:

-   grant_id
-   addon_id
-   service
-   period_start
-   period_end
-   daily_limit_tokens OR daily_limit_cost
-   status: active\|revoked\|expired

Service addon: - Tracks local usage - Enforces limits - Reports usage
periodically

Core: - Assigns grants - Adjusts budgets - Revokes when needed

------------------------------------------------------------------------

## 4. Revocation Mechanism

Core may revoke:

-   Token (by jti)
-   Grant (by grant_id)

Revocation distributed via:

-   MQTT retained topic
-   Periodic polling fallback

Addons must degrade gracefully upon revocation.

------------------------------------------------------------------------

## 5. Budget Strategy

Each service addon defines: - maximum daily capacity

Core assigns portions per addon needing service.

Example: AI addon daily capacity = 1,000,000 tokens\
Vision granted = 400,000\
Gmail automation granted = 50,000\
Others distributed accordingly

------------------------------------------------------------------------

## 6. Failure Modes

If Core unavailable: - Existing valid tokens remain usable until
expiry - Existing grants remain enforceable - No new grants issued

If Service addon unavailable: - Calling addon must degrade gracefully -
No blocking loops

------------------------------------------------------------------------

## 7. Security Principles

-   Least privilege scopes
-   Short token lifetimes
-   Revocation support
-   No secrets in MQTT
-   TLS required for remote deployments

# Synthia Distributed Architecture --- Core Structure

Version: 0.1\
Date: 2026-02-28

## 1. Core Role: Control Plane

Synthia Core is **not** in the data path of addons.\
It acts as:

-   Addon registry
-   Authentication + authorization authority
-   Token issuer
-   Policy & quota authority
-   Reverse proxy for browser → addon calls
-   Unified UI shell
-   Global settings manager
-   Telemetry aggregator

Core must NOT: - Relay sensor events - Relay AI inference traffic - Sit
in high-frequency data paths

------------------------------------------------------------------------

## 2. Addon Registry

Core maintains a persistent registry:

-   id
-   name
-   base_url
-   capabilities (string list)
-   health status
-   last_seen
-   auth_mode

Example capabilities: - vision.ingest - ai.classify - gmail.send -
storage.object

------------------------------------------------------------------------

## 3. Reverse Proxy Model

Browser → Core → Addon

Core proxies: - /api/addons/{id}/* - /addons/{id}/*

Addons may still expose standalone UI directly.

------------------------------------------------------------------------

## 4. MQTT Options

Core supports two install modes:

A. Local MQTT Addon\
- Runs broker locally (Mosquitto container) - Persistent storage -
Health monitoring

B. External MQTT Broker\
- Host/port/credentials provided during install - Connection test
required

Core may attempt: - mDNS `_mqtt._tcp` - common hostname probes -
fallback to local broker addon

------------------------------------------------------------------------

## 5. Distributed Addon Model

Addons may run on separate machines.

Core responsibilities: - Service discovery - Policy distribution - Token
issuing

Addon responsibilities: - Data ingestion - Local persistence -
Service-specific execution

Core must not disturb addon runtime operation.

------------------------------------------------------------------------

## 6. Supervisor Layer (Future)

Optional supervisor endpoints: - start - stop - restart - reload_config

Supervision is optional and must not be required for correctness.

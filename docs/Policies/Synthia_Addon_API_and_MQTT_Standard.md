# Synthia Addon API & MQTT Communication Standard

Version: 0.1\
Date: 2026-02-28

## 1. Required Addon HTTP Endpoints

GET /api/addon/meta\
GET /api/addon/health\
GET /api/addon/config/effective\
POST /api/addon/config\
GET /api/addon/capabilities

Optional: POST /api/addon/control/{action}

------------------------------------------------------------------------

## 2. Capability Naming Convention

Format: `<domain>`{=html}.`<service>`{=html}

Examples: - ai.classify - vision.ingest - gmail.send -
storage.object.write

------------------------------------------------------------------------

## 3. MQTT Telemetry Standards

### Discovery

Topic: synthia/addons/{id}/announce (retained)

Payload: - id - base_url - version - capabilities

### Health

synthia/addons/{id}/health (retained)

Payload: - status: healthy\|degraded\|offline - last_seen

### Policy Distribution

synthia/policy/grants/{service} synthia/policy/revocations/{addon_id}

Retained messages required.

------------------------------------------------------------------------

## 4. Telemetry Reporting (Addon → Core)

HTTP preferred: POST /api/telemetry/usage

Includes: - addon_id - service - tokens_used - cost_estimate - timestamp

Periodic batching allowed.

------------------------------------------------------------------------

## 5. Non-Interference Principle

-   Addons must function independently if core is unavailable.
-   Core must not be required for real-time processing.
-   Revocation must not crash addon execution.

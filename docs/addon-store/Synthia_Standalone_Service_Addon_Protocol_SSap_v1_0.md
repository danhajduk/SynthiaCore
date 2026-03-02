# Synthia Standalone Service Addon Protocol (SSAP) v1.0

**Status:** Draft – Canonical Specification  
**Applies to:** SynthiaCore, Synthia-Addon-Catalog, Standalone Service Addons  
**Aligned With:**  
- Synthia Addon Standard (SAS v1.1)  
- Synthia Addon API & MQTT Standard  
- Synthia Distributed Addon Spec v0.1  
- Synthia Tokens / Permissions / Quota Model  

---

# 1. Purpose

SSAP defines how **standalone_service** addons are:

- Installed
- Started / stopped
- Managed via Docker Compose
- Self-registered
- Health monitored
- Upgraded / rolled back

SSAP explicitly enforces:

- Non‑interference architecture
- Addon independence from Core availability
- MQTT-based self-registration
- Supervisor-based lifecycle reconciliation
- Artifact integrity verification (Option A signature model)

---

# 2. Architectural Roles

## 2.1 Core (Control Plane)

Core:
- Fetches catalog
- Verifies artifacts (hash + signature)
- Writes desired state files
- Issues tokens / quotas
- Maintains registry view (based on MQTT + optional phone-home)
- Provides UI & API

Core does **NOT**:
- Directly own container runtime state
- Require itself to be running for addon operation

---

## 2.2 Supervisor (Local Orchestrator)

A system service (systemd recommended) running alongside Core.

Responsibilities:
- Watches addon desired state files
- Reconciles desired vs actual runtime
- Generates docker-compose files
- Starts / stops containers
- Writes runtime state
- Performs optional local health checks

Supervisor must:
- Be optional (addon containers continue running if Supervisor stops)
- Never be required for runtime correctness

---

## 2.3 Standalone Addon (Data Plane)

A standalone_service addon must:

- Run independently of Core
- Self-register via MQTT retained announce
- Publish retained health topic
- Expose required HTTP endpoints
- Enforce local JWT validation for service tokens
- Continue functioning if Core is offline

---

# 3. Filesystem Layout

Default base directory (configurable via env):

SYNTHIA_ADDONS_DIR=../SynthiaAddons

Directory structure:

SynthiaAddons/
  services/
    <addon_id>/
      desired.json
      runtime.json
      versions/
        <version>/
          addon.tgz
          extracted/
          docker-compose.yml
          env/
      current -> versions/<version>

---

# 4. desired.json (Operator Intent)

Location:

../SynthiaAddons/services/<addon_id>/desired.json

Schema (SSAP v1.0):

{
  "ssap_version": "1.0",
  "addon_id": "mqtt",
  "mode": "standalone_service",

  "desired_state": "running",
  "channel": "stable",
  "pinned_version": null,

  "install_source": {
    "type": "catalog",
    "catalog_id": "official",
    "release": {
      "artifact_url": "https://.../addon.tgz",
      "sha256": "HEX64",
      "publisher_key_id": "publisher.danhajduk#2026-02",
      "signature": {
        "type": "ed25519",
        "value": "BASE64"
      }
    }
  },

  "runtime": {
    "orchestrator": "docker_compose",
    "project_name": "synthia-addon-mqtt",
    "network": "synthia_net",
    "ports": [
      { "host": 9002, "container": 9002, "proto": "tcp", "purpose": "http_api" }
    ]
  },

  "config": {
    "env": {
      "CORE_URL": "http://127.0.0.1:9001",
      "SYNTHIA_ADDON_ID": "mqtt"
    }
  }
}

Rules:
- Core writes this file.
- Supervisor reads this file.
- It represents desired system state only.
- Changing desired_state triggers reconciliation.

---

# 5. runtime.json (Actual State)

Location:

../SynthiaAddons/services/<addon_id>/runtime.json

{
  "ssap_version": "1.0",
  "addon_id": "mqtt",
  "active_version": "0.1.2",
  "state": "running",
  "last_action": {
    "type": "start",
    "at": "2026-03-01T01:10:00Z",
    "ok": true,
    "message": null
  },
  "docker": {
    "project_name": "synthia-addon-mqtt",
    "compose_file": ".../docker-compose.yml"
  },
  "health": {
    "last_checked": "2026-03-01T01:11:00Z",
    "status": "healthy"
  }
}

Rules:
- Supervisor writes runtime.json.
- Core reads runtime.json for UI display.
- runtime.json must never be manually edited.

---

# 6. Supervisor Reconciliation Algorithm

Loop interval: configurable (default 5 seconds).

For each addon:

1. Load desired.json
2. If desired_state == "running":
   - Verify artifact exists
   - Verify SHA-256 matches catalog
   - Verify signature (Option A)
   - Extract artifact if needed
   - Generate docker-compose.yml if missing
   - Run docker compose up -d
3. If desired_state == "stopped":
   - Run docker compose down
4. Update runtime.json
5. Optional: perform HTTP health check

Supervisor MUST:
- Never require Core to be reachable
- Never bypass artifact verification
- Never escalate container privileges by default

---

# 7. Self-Registration Protocol

Standalone addons must self-register when available.

MQTT Announce (Retained):

Topic:
synthia/addons/{addon_id}/announce

Payload:
{
  "id": "mqtt",
  "version": "0.1.2",
  "base_url": "http://localhost:9002",
  "capabilities": ["mqtt.control_plane"]
}

MQTT Health (Retained):

Topic:
synthia/addons/{addon_id}/health

Payload:
{
  "status": "healthy",
  "last_seen": "2026-03-01T01:11:00Z"
}

Required HTTP Endpoints:

GET /api/addon/health
GET /api/addon/capabilities
GET /api/addon/version
GET /api/addon/permissions

---

# 8. Signature Model (Option A)

Release entry includes:

- sha256 (hex)
- signature over SHA-256 digest bytes (ed25519)

Verification order:

1. Download artifact
2. Compute SHA-256
3. Compare with catalog sha256
4. Verify signature over digest bytes
5. Extract artifact

Containers must NOT be started before verification passes.

---

# 9. Upgrade Strategy

Default strategy: replace

Upgrade flow:
1. Download + verify new version
2. Extract to versions/<new_version>
3. Generate compose
4. Stop old containers
5. Start new containers
6. Update symlink
7. Update runtime.json

Rollback supported if previous version still exists.

---

# 10. Security Requirements

Supervisor must:
- Use non-root containers where possible
- Avoid privileged mode
- Use dedicated Docker network (e.g. synthia_net)
- Inject service token via env file
- Not expose ports publicly by default

Addon must:
- Validate JWT service token
- Enforce quota locally
- Never depend on Core availability for runtime correctness

---

# 11. Future Extensions (Not in v1)

- Multi-host distributed supervisor
- Kubernetes support
- Delta artifact updates
- Encrypted private catalogs

---

# 12. SSAP JSON Schemas

desired.schema.json

{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["ssap_version", "addon_id", "desired_state"],
  "properties": {
    "ssap_version": { "const": "1.0" },
    "addon_id": { "type": "string" },
    "desired_state": { "enum": ["running", "stopped"] }
  }
}

runtime.schema.json

{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["ssap_version", "addon_id", "state"],
  "properties": {
    "ssap_version": { "const": "1.0" },
    "addon_id": { "type": "string" },
    "state": { "enum": ["running", "stopped", "error", "installing"] }
  }
}

---

End of SSAP v1.0

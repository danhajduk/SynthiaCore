# Synthia Addon Standard (SAS) — Catalog / Manifest / Core Contract (v1.1)

Last Updated: 2026-03-07 14:51 US/Pacific

**Status:** Draft (intended to become the *single source of truth* for Synthia addon packaging + store distribution)  
**Applies to repos:** `SynthiaCore`, `Synthia-Addon-Catalog`, any addon repo (e.g. `Synthia-MQTT`)  
**Signature model:** **Option A** — signature over the artifact SHA-256 (see §6)

> If you are reading this as “Codex instructions”: treat this document as authoritative.  
> Do not invent fields. Do not rename fields. Do not omit required validation steps.

---

## 0) Executive summary

There are **three** distinct but related documents in the Synthia addon ecosystem:

1) **Addon Package Manifest** (`manifest.json`)  
   - Lives **inside the addon repo** and inside the **released artifact** (`addon.tgz`).  
   - Describes the addon **identity**, **compatibility**, **permissions**, and **entrypoints**.

2) **Addon Store Catalog Index** (`catalog/v1/index.json`)  
   - Lives in **Synthia-Addon-Catalog**.  
   - Lists **addons** and their **releases**.  
   - Each release points to an artifact URL + integrity hash + signature metadata.

3) **Publishers Registry** (`catalog/v1/publishers.json`)  
   - Lives in **Synthia-Addon-Catalog**.  
   - Defines **publishers** and their **public signing keys** (key rotation, revocation).

**Core (SynthiaCore) is the enforcement point**: it validates the catalog, downloads artifacts, verifies integrity + signatures, reads `manifest.json`, validates permissions/compatibility, then installs.

---

## 1) Directory layout

### 1.1 Addon repository layout (example)
An addon repository (e.g. `Synthia-MQTT`) must include:

```
<addon-repo>/
  manifest.json                 # REQUIRED
  app/                          # optional (for service profile)
  frontend/                     # optional (for ui profile)
  requirements.txt              # optional
  ...
```

A released addon artifact (`addon.tgz`) **must contain `manifest.json` at the root** of the archive.

### 1.2 Catalog repository layout
`Synthia-Addon-Catalog` stores:

```
Synthia-Addon-Catalog/
  catalog/
    v1/
      index.json                # REQUIRED
      publishers.json           # REQUIRED
      schemas/                  # RECOMMENDED (strongly)
        addon-manifest.schema.json
        catalog-index.schema.json
        publishers.schema.json
      README.md                 # optional human doc
```

---

## 2) Lifecycle and trust chain

### 2.1 Release lifecycle (authoritative steps)

**Publisher (addon author) produces release:**
1. Build `addon.tgz` artifact.
2. Compute `sha256` of the artifact bytes.
3. Sign the **sha256 digest bytes** using publisher’s private key (Option A).
4. Upload artifact to a stable URL (commonly GitHub release asset).
5. Submit PR to `Synthia-Addon-Catalog` adding release entry to `catalog/v1/index.json`.

**Catalog (Synthia-Addon-Catalog) holds “what is approved”:**
- The catalog index is the list of releases Core is allowed to install.
- The publishers registry is the list of public keys Core trusts.

**Core (SynthiaCore) installs:**
1. Fetch `catalog/v1/index.json`.
2. Fetch `catalog/v1/publishers.json`.
3. Select a release compatible with the running Core version.
4. Download artifact from `artifact.url`.
5. Verify artifact `sha256` matches the release entry.
6. Verify signature (Option A) using the public key referenced by `publisher_key_id`.
7. Extract artifact and read `manifest.json`.
8. Validate manifest schema + compatibility + permissions.
9. Install/mount the addon according to `package_profile` and `entrypoints`.

### 2.2 What is trusted vs untrusted

| Data | Source | Trust | How validated |
|---|---|---|---|
| `publishers.json` | Catalog | Trusted once fetched | Must be schema-valid; keys used for verification |
| Release entry (index.json) | Catalog | Trusted *as a pointer* | Must be schema-valid; signature verification ties it to publisher |
| Artifact bytes | Remote URL | Untrusted | Hash + signature verification |
| `manifest.json` inside artifact | Artifact | Untrusted until hash+sig pass | Manifest schema validation + cross-checks |

**Rule:** Core MUST NOT parse or act on `manifest.json` until the artifact hash + signature have been verified.

---

## 3) Addon Package Manifest (`manifest.json`) — spec

### 3.1 Required file name and location
- File name must be exactly: `manifest.json`
- Location must be: repo root AND artifact root.

### 3.2 Schema versioning
- `schema_version` is required.
- This document defines **manifest schema v1.1**.

### 3.3 Manifest fields (v1.1)

```jsonc
{
  "schema_version": "1.1",

  // identity
  "id": "mqtt",
  "name": "Hexe MQTT",
  "description": "MQTT integration layer for Synthia Core",
  "version": "0.1.0",

  // how Core should run/mount it
  "package_profile": "standalone_service",

  // compatibility & constraints
  "compatibility": {
    "core_min_version": "0.6.0",
    "core_max_version": null,
    "dependencies": [],
    "conflicts": []
  },

  // capability requests (Core-enforced)
  "permissions": [
    "network.egress",
    "mqtt.publish",
    "mqtt.subscribe"
  ],

  // optional packaging hints (Core should ignore unknown paths)
  "paths": [
    "manifest.json",
    "frontend",
    "app",
    "requirements.txt"
  ],

  // entrypoints depend on package_profile
  "entrypoints": {
    "service": "app/main.py",
    "ui": "frontend"
  },

  // publisher identity (optional; catalog is primary authority)
  "publisher": {
    "id": "publisher.danhajduk"
  }
}
```

### 3.4 Field definitions (normative)

**Identity**
- `id` *(string, required)*: addon identifier, **lowercase**, `[a-z0-9_]+`, stable across versions.
- `name` *(string, required)*: human-friendly.
- `description` *(string, optional)*: human-friendly.
- `version` *(string, required)*: semver (`MAJOR.MINOR.PATCH`).

**Package profile**
- `package_profile` *(string, required)*: tells Core how to mount it.
- Allowed values (v1.1):
  - `embedded_addon` — addon runs within Core process (import/mount router + UI).
  - `standalone_service` — addon runs as separate service/container managed by Core.
  - `frontend_only` — addon provides UI only.
  - `backend_only` — addon provides backend only.

> **Note:** `embedded_addon` aligns with Synthia “addons folder contains backend+frontend” architecture.  
> `standalone_service` aligns with “service addon” model (MQTT, Vision, etc.).

**Compatibility**
- `compatibility.core_min_version` *(string, required)*: minimum Core version.
- `compatibility.core_max_version` *(string|null, required)*: max Core version or null for open-ended.
- `compatibility.dependencies` *(array, optional, default `[]`)*: list of addon IDs required.
- `compatibility.conflicts` *(array, optional, default `[]`)*: list of addon IDs not allowed.

**Permissions**
- `permissions` *(array of strings, required)*: Core must prompt/enforce (policy authority).
- Allowed permission vocabulary is defined in Core. Catalog/manifests must not invent permissions.

**Paths**
- `paths` *(array of strings, optional)*: packaging hint only.  
  Core MAY ignore this field. Do not use for security decisions.

**Entrypoints**
- `entrypoints` *(object, optional depending on profile)*:  
  - For `embedded_addon`: may include `backend` module path and `ui` folder.
  - For `standalone_service`: should include `service` (main executable / module path).
  - For `frontend_only`: should include `ui`.
  - For `backend_only`: should include `backend`.

**Publisher**
- `publisher.id` *(string, optional)*: informative only.  
  **Catalog release entry is authoritative** for publisher via `publisher_key_id`.

### 3.5 Backward compatibility (aliases)
Core may support legacy permission aliases during migration, but the canonical v1.1 manifest must use:
- `network.egress` not `network.outbound`
- `network.ingress` not `network.inbound`
- `mqtt.publish` / `mqtt.subscribe` not `mqtt.client`

If Core supports aliases, it MUST normalize them to canonical values internally.

---

## 4) Catalog Index (`catalog/v1/index.json`) — spec

### 4.1 Purpose
The catalog index lists addons and their releases. Each release is a concrete installable artifact.

### 4.2 Schema versioning
- `schema_version` required; this document defines catalog index schema v1.0.

### 4.3 Index format (normative)

```jsonc
{
  "schema_version": "1.0",
  "updated_at": "2026-03-01T00:00:00Z",

  "addons": [
    {
      "addon_id": "mqtt",
      "name": "Hexe MQTT",
      "description": "MQTT integration layer for Synthia Core",
      "repo": "https://github.com/danhajduk/Synthia-MQTT",
      "publisher_id": "publisher.danhajduk",

      "channels": {
        "stable": [
          {
            "version": "0.1.0",
            "core_compat": { "min": "0.6.0", "max": null },

            "artifact": {
              "type": "github_release_asset",
              "url": "https://github.com/danhajduk/Synthia-MQTT/releases/download/v0.1.0/addon.tgz"
            },

            "sha256": "HEX_SHA256_OF_ARTIFACT_BYTES",
            "publisher_key_id": "publisher.danhajduk#2026-02",

            "signature": {
              "type": "ed25519",
              "value": "BASE64_SIGNATURE_OVER_SHA256_DIGEST_BYTES"
            },

            "released_at": "2026-02-28T00:00:00Z",

            // OPTIONAL: integrity pin for manifest.json content inside artifact
            "manifest_sha256": "HEX_SHA256_OF_MANIFEST_JSON_BYTES"
          }
        ],

        "beta": [],
        "nightly": []
      }
    }
  ]
}
```

### 4.4 Channel semantics (normative)
- `channels` is an object mapping channel name → array of releases.
- Required channels in v1.0: `stable` (must exist; may be empty).
- Recommended additional channels: `beta`, `nightly`.
- Core should default to `stable` unless configured otherwise.

### 4.5 Release selection rules (normative)
When selecting a release for installation/upgrade, Core MUST:
1. Filter releases where `core_compat.min <= core_version` AND (`core_compat.max` is null OR `core_version <= core_compat.max`)
2. Prefer highest semantic `version`.
3. If multiple channels are enabled, evaluate in user-configured precedence order (e.g., stable > beta).

---

## 5) Publishers Registry (`catalog/v1/publishers.json`) — spec

### 5.1 Purpose
Defines trusted publishers and their public keys used to verify release signatures.

### 5.2 Format (normative)

```jsonc
{
  "schema_version": "1.0",
  "updated_at": "2026-03-01T00:00:00Z",

  "publishers": [
    {
      "publisher_id": "publisher.danhajduk",
      "display_name": "Dan Hajduk",

      "website": null,

      "contact": {
        "email": null
      },

      "keys": [
        {
          "key_id": "publisher.danhajduk#2026-02",
          "status": "active",

          "algorithm": "ed25519",
          "public_key": "BASE64_OR_HEX_PUBLIC_KEY",

          "created_at": "2026-02-01T00:00:00Z",
          "not_before": "2026-02-01T00:00:00Z",
          "not_after": null,

          "revoked_at": null,
          "revocation_reason": null
        }
      ]
    }
  ]
}
```

### 5.3 Key rotation and revocation (normative)
- A publisher may have multiple keys.
- Core MUST:
  - Reject any key where `status == "revoked"`.
  - Reject if current time < `not_before`.
  - Reject if `not_after` is not null and current time > `not_after`.
- `status == "deprecated"` may be accepted for existing releases but should not be used for new releases.

---

## 6) Signature model — Option A (artifact SHA-256)

### 6.1 What is signed (normative)
Each catalog release entry includes:
- `sha256`: hex-encoded SHA-256 digest of the **artifact bytes**.
- `signature`: signature over the SHA-256 digest **bytes** (not the hex string) using the key referenced by `publisher_key_id`.

**Canonical:**  
`sig = Sign(private_key, digest_bytes)`  
where `digest_bytes = SHA256(artifact_bytes)`.

### 6.2 Verification steps (normative, Core)
Core MUST verify in this order:
1. Download artifact bytes.
2. Compute `digest_bytes = SHA256(artifact_bytes)`.
3. Compare hex digest to `release.sha256`. If mismatch → fail.
4. Find `publisher_key_id` in publishers.json; extract `public_key` + `algorithm`.
5. Verify signature using algorithm over `digest_bytes`. If fail → fail.
6. Only after passing, extract artifact and read manifest.

### 6.3 Signature encoding (normative)
- `signature.value` is Base64 of signature bytes.
- `sha256` is lowercase hex (64 chars).

---

## 7) Cross-document invariants (must hold)

Core MUST enforce these invariants:

1. `catalog.addons[].addon_id` MUST equal `manifest.id` inside artifact.  
   - If mismatch, installation fails (prevents “bait-and-switch” artifact).

2. `catalog release.version` MUST equal `manifest.version` inside artifact.  
   - If mismatch, installation fails.

3. `catalog.addons[].publisher_id` MUST equal `manifest.publisher.id` if manifest publisher is present.  
   - If manifest omits publisher, this check is skipped.

4. Core MUST enforce permissions from **manifest.permissions** (canonical).  
   - Catalog does not grant permissions; it only distributes.

5. Core MUST apply compatibility rules using both:
   - Catalog `core_compat` (fast filter) AND
   - Manifest `compatibility` (deep validation).

6. Unknown fields:  
   - Catalog files: unknown fields should be rejected (to keep the contract strict).  
   - Manifest: unknown fields MAY be ignored, but only if `schema_version` supports extension. Prefer strict validation if possible.

---

## 8) JSON Schemas (copy these into catalog/v1/schemas/)

> These schemas are intentionally strict to avoid drift.  
> Update schema_version when making incompatible changes.

### 8.1 `addon-manifest.schema.json` (v1.1)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://synthia.local/schemas/addon-manifest.schema.json",
  "title": "Synthia Addon Manifest",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "id", "name", "version", "package_profile", "compatibility", "permissions"],
  "properties": {
    "schema_version": { "type": "string", "const": "1.1" },

    "id": {
      "type": "string",
      "pattern": "^[a-z0-9_]+$",
      "minLength": 1
    },
    "name": { "type": "string", "minLength": 1 },
    "description": { "type": ["string", "null"] },

    "version": {
      "type": "string",
      "pattern": "^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:[-+][0-9A-Za-z.-]+)?$"
    },

    "package_profile": {
      "type": "string",
      "enum": ["embedded_addon", "standalone_service", "frontend_only", "backend_only"]
    },

    "compatibility": {
      "type": "object",
      "additionalProperties": false,
      "required": ["core_min_version", "core_max_version"],
      "properties": {
        "core_min_version": {
          "type": "string",
          "pattern": "^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:[-+][0-9A-Za-z.-]+)?$"
        },
        "core_max_version": {
          "type": ["string", "null"],
          "pattern": "^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:[-+][0-9A-Za-z.-]+)?$"
        },
        "dependencies": {
          "type": "array",
          "items": { "type": "string", "pattern": "^[a-z0-9_]+$" },
          "default": []
        },
        "conflicts": {
          "type": "array",
          "items": { "type": "string", "pattern": "^[a-z0-9_]+$" },
          "default": []
        }
      }
    },

    "permissions": {
      "type": "array",
      "minItems": 0,
      "items": { "type": "string", "minLength": 1 },
      "uniqueItems": true
    },

    "paths": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    },

    "entrypoints": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "service": { "type": "string", "minLength": 1 },
        "backend": { "type": "string", "minLength": 1 },
        "ui": { "type": "string", "minLength": 1 }
      }
    },

    "publisher": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id"],
      "properties": {
        "id": { "type": "string", "minLength": 1 }
      }
    }
  }
}
```

### 8.2 `publishers.schema.json` (v1.0)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://synthia.local/schemas/publishers.schema.json",
  "title": "Synthia Publishers Registry",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "updated_at", "publishers"],
  "properties": {
    "schema_version": { "type": "string", "const": "1.0" },
    "updated_at": { "type": "string", "format": "date-time" },
    "publishers": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["publisher_id", "display_name", "keys"],
        "properties": {
          "publisher_id": { "type": "string", "minLength": 1 },
          "display_name": { "type": "string", "minLength": 1 },
          "website": { "type": ["string", "null"] },
          "contact": {
            "type": "object",
            "additionalProperties": false,
            "required": ["email"],
            "properties": {
              "email": { "type": ["string", "null"] }
            }
          },
          "keys": {
            "type": "array",
            "minItems": 1,
            "items": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "key_id", "status", "algorithm", "public_key",
                "created_at", "not_before", "not_after",
                "revoked_at", "revocation_reason"
              ],
              "properties": {
                "key_id": { "type": "string", "minLength": 1 },
                "status": { "type": "string", "enum": ["active", "deprecated", "revoked"] },
                "algorithm": { "type": "string", "enum": ["ed25519"] },
                "public_key": { "type": "string", "minLength": 1 },
                "created_at": { "type": "string", "format": "date-time" },
                "not_before": { "type": "string", "format": "date-time" },
                "not_after": { "type": ["string", "null"], "format": "date-time" },
                "revoked_at": { "type": ["string", "null"], "format": "date-time" },
                "revocation_reason": { "type": ["string", "null"] }
              }
            }
          }
        }
      }
    }
  }
}
```

### 8.3 `catalog-index.schema.json` (v1.0)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://synthia.local/schemas/catalog-index.schema.json",
  "title": "Synthia Addon Catalog Index",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "updated_at", "addons"],
  "properties": {
    "schema_version": { "type": "string", "const": "1.0" },
    "updated_at": { "type": "string", "format": "date-time" },

    "addons": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["addon_id", "name", "repo", "publisher_id", "channels"],
        "properties": {
          "addon_id": { "type": "string", "pattern": "^[a-z0-9_]+$", "minLength": 1 },
          "name": { "type": "string", "minLength": 1 },
          "description": { "type": ["string", "null"] },
          "repo": { "type": "string", "minLength": 1 },
          "publisher_id": { "type": "string", "minLength": 1 },

          "channels": {
            "type": "object",
            "additionalProperties": false,
            "required": ["stable"],
            "properties": {
              "stable": { "$ref": "#/$defs/releases" },
              "beta": { "$ref": "#/$defs/releases" },
              "nightly": { "$ref": "#/$defs/releases" }
            }
          }
        }
      }
    }
  },

  "$defs": {
    "releases": {
      "type": "array",
      "items": { "$ref": "#/$defs/release" }
    },

    "release": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "version", "core_compat", "artifact", "sha256",
        "publisher_key_id", "signature", "released_at"
      ],
      "properties": {
        "version": {
          "type": "string",
          "pattern": "^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:[-+][0-9A-Za-z.-]+)?$"
        },

        "core_compat": {
          "type": "object",
          "additionalProperties": false,
          "required": ["min", "max"],
          "properties": {
            "min": {
              "type": "string",
              "pattern": "^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:[-+][0-9A-Za-z.-]+)?$"
            },
            "max": {
              "type": ["string", "null"],
              "pattern": "^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)"
            }
          }
        },

        "artifact": {
          "type": "object",
          "additionalProperties": false,
          "required": ["type", "url"],
          "properties": {
            "type": { "type": "string", "enum": ["github_release_asset", "http"] },
            "url": { "type": "string", "minLength": 1 }
          }
        },

        "sha256": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
        "publisher_key_id": { "type": "string", "minLength": 1 },

        "signature": {
          "type": "object",
          "additionalProperties": false,
          "required": ["type", "value"],
          "properties": {
            "type": { "type": "string", "enum": ["ed25519"] },
            "value": { "type": "string", "minLength": 1 }
          }
        },

        "released_at": { "type": "string", "format": "date-time" },

        "manifest_sha256": { "type": "string", "pattern": "^[a-f0-9]{64}$" }
      }
    }
  }
}
```

---

## 9) Implementation checklist (Core + tooling)

### 9.1 Core (SynthiaCore) MUST implement
- Fetch + schema-validate `index.json` and `publishers.json`.
- Release selection logic per §4.5.
- Artifact download + SHA-256 validation.
- Signature verification per §6.
- Extract and parse `manifest.json` only after verification.
- Validate `manifest.json` per `addon-manifest.schema.json`.
- Enforce invariants per §7.
- Enforce permissions (policy authority).

### 9.2 Catalog (Synthia-Addon-Catalog) RECOMMENDED
- Commit the three JSON schemas in `catalog/v1/schemas/`.
- Add CI that validates `index.json` and `publishers.json` against schemas.

### 9.3 Addon repos MUST
- Include `manifest.json` matching schema v1.1.
- Bump manifest `version` per release.
- Ensure `manifest.id` is stable and matches catalog `addon_id`.

---

## 10) Reference examples (minimal real-world)

### 10.1 Minimal manifest for embedded addon
```json
{
  "schema_version": "1.1",
  "id": "email",
  "name": "Email Integration",
  "description": "Handles email workflows",
  "version": "0.1.0",
  "package_profile": "embedded_addon",
  "compatibility": { "core_min_version": "0.6.0", "core_max_version": null, "dependencies": [], "conflicts": [] },
  "permissions": [],
  "entrypoints": { "backend": "backend/addon.py", "ui": "frontend" }
}
```

### 10.2 Minimal catalog entry for that addon
```json
{
  "schema_version": "1.0",
  "updated_at": "2026-03-01T00:00:00Z",
  "addons": [
    {
      "addon_id": "email",
      "name": "Email Integration",
      "description": "Handles email workflows",
      "repo": "https://github.com/example/Synthia-Email",
      "publisher_id": "publisher.example",
      "channels": {
        "stable": [
          {
            "version": "0.1.0",
            "core_compat": { "min": "0.6.0", "max": null },
            "artifact": { "type": "http", "url": "https://example.com/addons/email/addon.tgz" },
            "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "publisher_key_id": "publisher.example#2026-01",
            "signature": { "type": "ed25519", "value": "BASE64..." },
            "released_at": "2026-03-01T00:00:00Z"
          }
        ],
        "beta": [],
        "nightly": []
      }
    }
  ]
}
```

---

## 11) Non-goals (explicitly out of scope)
- Payment / licensing / entitlements
- Private catalogs (authentication)
- Delta updates / patching
- Runtime permission prompts UX
- Multi-arch artifact selection

These can be added later under new schema versions.

---

## 12) Change control
- Any backward-incompatible change increments:
  - manifest `schema_version` (e.g. 1.2)
  - catalog `schema_version` (e.g. 2.0)
- Schemas must be updated in lockstep with Core’s validation logic.

---

**End of standard.**

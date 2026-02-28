# Addon Store Architecture (Phase 2)

Date: 2026-02-28
Status: Phase 2 remote catalog + install flow implemented

## Official Source
- Official store source id: `official`
- Source type: `github_raw`
- Base URL: `https://raw.githubusercontent.com/danhajduk/Synthia-Addon-Catalog/main`
- Required remote files:
  - `catalog/v1/index.json`
  - `catalog/v1/index.json.sig`
  - `catalog/v1/publishers.json`
  - `catalog/v1/publishers.json.sig`

## Package Structure
- `backend/app/store/models.py`
  - Manifest and contract models (`AddonManifest`, `ReleaseManifest`, `CompatibilitySpec`, `SignatureBlock`)
  - Semver validation and explicit permission allowlist
  - `GET /api/store/schema` JSON schema export
- `backend/app/store/signing.py`
  - SHA256 checksum verification
  - RSA signature verification
  - Fail-closed structured verification errors
  - Pre-enable verification hook
- `backend/app/store/resolver.py`
  - Core version compatibility checks
  - Dependency presence validation
  - Conflict detection
  - Deterministic resolution ordering
- `backend/app/store/router.py`
  - Lifecycle endpoints for install/update/uninstall/status
  - Atomic unpack/swap/rollback flow
  - Safe archive extraction checks
  - SQLite audit store (`store_audit_log`)
- `backend/app/store/catalog.py`
  - Source-backed catalog fetch/cache client
  - Signature verification for `index.json` and `publishers.json`
  - Last-known-good catalog reads and status metadata

## Trust Chain
1. Core refreshes a source by fetching `index.json`, `index.json.sig`, `publishers.json`, `publishers.json.sig`.
2. Core verifies catalog signatures using configured store public keys (rotation-ready, any-key-pass).
3. On catalog verification failure, refresh fails closed and existing cached catalog remains active.
4. Install-from-catalog resolves a release from cached `index.json` and publisher key from cached `publishers.json`.
5. Core verifies artifact `sha256` and detached `release_sig` with the selected enabled publisher key (`rsa-sha256` only).
6. Core validates compatibility constraints (core version, dependencies, conflicts).
7. Only verified releases proceed into atomic install/update lifecycle.

## Install Lifecycle
1. Install/update request is authenticated (admin token).
2. Request mode:
  - Local path mode (existing): `package_path` + manifest + publisher key.
  - Catalog mode (Phase 2): `source_id` + `addon_id` + optional `version`.
3. Catalog mode resolves latest compatible release when `version` is omitted.
4. Core downloads artifact with timeout, redirect, and size limits.
5. Verification pipeline runs first (checksum + detached signature + compatibility resolver).
6. Package is extracted to staging with path traversal protection.
7. Install:
  - New addon path is atomically moved into `addons/<id>`.
8. Update:
  - Existing addon directory is atomically backed up.
  - New directory is atomically moved into place.
  - On failure, backup is restored.
9. Uninstall:
  - Addon directory is atomically moved to transient delete path then removed.
  - On failure, directory is restored.
10. Action result is recorded into `store_audit_log`.

## Cache + Last-Known-Good
- Cache location: `runtime/store/cache/<source_id>/`
- Cached files:
  - `index.json`
  - `index.json.sig`
  - `publishers.json`
  - `publishers.json.sig`
  - `metadata.json` (`status`, `last_success_at`, `last_error_at`, `last_error_message`)
- Successful refresh atomically replaces cache content.
- Failed refresh preserves previous cache and marks error state for operator visibility.

## Dependency Resolution Model
- Resolver input:
  - `core_version`
  - requested addon manifest (`dependencies`, `conflicts`, min/max core versions)
  - installed addon set
- Enforcement:
  - Blocks if core version is below minimum or above maximum.
  - Blocks if required dependencies are missing.
  - Blocks if conflicts are already installed.
  - Blocks if the manifest internally overlaps dependency and conflict sets.
- Output:
  - Deterministic sorted dependency/conflict sets for predictable behavior.

## Future Billing Hook Points
- Add entitlement validation before lifecycle mutation in install/update endpoints.
- Extend audit records with entitlement/license decision fields.
- Add pricing and license metadata to catalog records.

## Future Sandbox Hook Points
- Validate requested addon permissions against policy before install/enable.
- Bind runtime sandbox profile from declared permissions.
- Block enablement if permission grant policy is not satisfied.

## Future Telemetry Hook Points
- Emit store lifecycle telemetry events (install attempts, failures, updates, uninstalls).
- Add catalog interaction telemetry (search/filter/install conversion).
- Correlate store audit entries with telemetry event IDs.

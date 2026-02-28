# Addon Store Product Requirements (Phase 2)

Date: 2026-02-28
Status: Phase 2 remote catalog + install requirements

## Scope
This document defines product requirements for Phase 2 of the official Synthia addon store. Focus is remote catalog trust, cached operations, and install-from-catalog security. Billing/reviews/publisher portal UX remain out of scope.

## Official Catalog Source
- Official source id is `official`.
- Source base URL is `https://raw.githubusercontent.com/danhajduk/Synthia-Addon-Catalog/main`.
- Core must fetch and verify:
  - `catalog/v1/index.json`
  - `catalog/v1/index.json.sig`
  - `catalog/v1/publishers.json`
  - `catalog/v1/publishers.json.sig`

## Roles
- `admin`: Full control over store policy, trusted keys, approval state, and install/update/uninstall operations.
- `operator`: Day-2 operations role for installs, updates, rollbacks, and incident handling without full policy authority.
- `publisher`: Produces addon packages and release metadata; cannot force install into core without approval path.
- `org-restricted`: Consumer context where installable addons are constrained by organization policy allowlists/denylists.

## Install Flow
1. User or automation requests install using either local-path mode or catalog mode.
2. Catalog mode request is `source_id` + `addon_id` + optional `version`.
3. Core resolves release from cached `index.json` (latest compatible when version is not provided).
4. Core downloads artifact and verifies `sha256` matches catalog metadata.
5. Core resolves `release.publisher_key_id` in cached `publishers.json` and requires key to be enabled.
6. Core verifies detached artifact signature (`release_sig`) using publisher public key (`rsa-sha256` only).
7. Core validates compatibility (core version, dependencies, conflicts, permissions).
8. Core performs atomic install into addon directory with rollback guard.
9. Core records structured audit log for download, verification, install, and failures.

## Trust Model
- Core is the trust anchor for install decisions.
- Store catalog integrity is verified by store operator signatures on `index.json` and `publishers.json`.
- Publisher identity is verified through detached artifact signature trust from `publishers.json` keys.
- Every release must include artifact checksum + detached signature metadata.
- Verification is fail-closed: invalid/missing catalog signatures, publisher keys, release signatures, or checksums block install.
- Policy and role checks must run before enabling installed addons.

## Cache and Availability Requirements
- Core must keep a last-known-good catalog cache per source.
- Refresh failures must not overwrite valid cache content.
- `GET /api/store/catalog` must surface catalog status and last error details.
- If no valid cache exists and refresh fails, catalog reads return empty list with error status.

## Billing Scope (Stub)
- Billing is out of scope for Phase 2 implementation.
- Requirements for future phases:
- Support free and paid addon metadata flags.
- Add entitlement validation hook in install/update path.
- Preserve auditability for license/entitlement decisions.

## Security Assumptions
- Core host is already access-controlled and monitored.
- Admin credentials are managed outside this spec (existing auth baseline).
- Unknown/undeclared permissions are denied by default.
- No install bypass flags are allowed in production path.
- All install/update/uninstall failures must be captured in audit logs.

## Offline Install Considerations
- Support air-gapped installs from local signed package files.
- Signature verification must work without online dependency.
- Catalog sync can be optional; local install path must not require internet at execution time.
- Operator must be able to pre-stage trusted keys and package bundles.

## Future Marketplace Model
- Central catalog service with discovery, categories, and publisher metadata.
- Approval workflow before org-wide availability.
- Entitlements, billing, and compliance checks as pluggable policy hooks.
- Ratings/reviews and abuse reporting added only after trust + security baseline is stable.

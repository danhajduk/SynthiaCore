# Distributed Addons Policy Alignment Baseline

This document maps the current implementation to the policy set in `docs/Policies/` and identifies the remaining structural alignment work.

## Policy References
- `docs/Policies/Synthia_Distributed_Addon_Spec_v0_1.md`
- `docs/Policies/Synthia_Distributed_Addons_Sequence_Diagrams_v0_1.md`
- `docs/Policies/Synthia_Distributed_Addons_Implementation_Checklist_v0_1.md`
- `docs/Policies/Synthia_Core_Structure.md`
- `docs/Policies/Synthia_Addon_API_and_MQTT_Standard.md`
- `docs/Policies/Synthia_Tokens_Permissions_Quota_Model.md`

## Current Alignment Snapshot
| Area | Policy Expectation | Current State | Status |
|---|---|---|---|
| Core role | Control-plane only | Registry/proxy/policy/auth/telemetry/services implemented; no high-frequency data relay in core | Aligned |
| Addon contract endpoints | Required addon API endpoints | Discovery enforces required routes in `backend/app/addons/discovery.py` | Aligned |
| Registry persistence | Persistent addon registry model | Remote registry persistence and CRUD available (`/api/admin/addons/registry`, `/api/addons/registry/*`) | Aligned |
| Browser proxy | `/api/addons/{id}/*` and UI proxy | API proxy exists at `/api/addons/{id}/*`; UI proxy now available at both `/addons/{id}/*` and legacy `/ui/addons/{id}/*` | Aligned |
| MQTT manager | Status/test/restart and subscriptions | `/api/system/mqtt/status|test|restart` plus topic subscriptions implemented | Aligned |
| Core MQTT info topic | Retained `synthia/core/mqtt/info` publication | Auto-published on successful MQTT connect/restart with sanitized broker metadata and heartbeat timestamp | Aligned |
| Service resolution | Capability-based service resolution endpoint | `/api/services/resolve` implemented (registry + catalog fallback) | Aligned |
| Service tokens | Service-to-service JWT issuance | `/api/auth/service-token` now supports constrained service-principal issuance (`X-Service-Principal-Id`/`X-Service-Principal-Secret`) in addition to admin issuance | Aligned |
| Policy grants schema | General limits (`max_requests`, `max_tokens`, `max_cost_cents`, `max_bytes`) | API/persistence/MQTT grant payloads now use the policy limit keys; legacy `max_units`/`burst` inputs are normalized for compatibility | Aligned |
| Revocation topic model | Revocation keyed by both consumer and grant | Core now publishes retained revocations on `consumer_addon_id` and `grant_id` topics, plus legacy `{id}` compatibility topic | Aligned |
| Addon package profiles | Clear embedded-addon vs standalone-service handling | Release manifests now carry `package_profile`; catalog installs enforce `embedded_addon` and return explicit standalone-service deployment guidance when unsupported | Aligned |

## Gap-to-Task Mapping
- None. Tasks 43-48 are complete as of 03/01/2026.

## Notes
- This baseline is intentionally implementation-focused and is updated as each gap task lands.
- Policy files remain the source of truth for target architecture decisions.
- For `catalog_package_layout_invalid` diagnostics, see `docs/distributed_addons/catalog_package_layout_invalid.md`.
- For `catalog_package_profile_unsupported` diagnostics, see `docs/distributed_addons/catalog_package_profile_unsupported.md`.
- Addon Store standalone remediation action cards now include this diagnostics doc path directly for operator triage.
- Standalone `/api/store/install` regression coverage now includes mode mismatch, runtime indicator responses, artifact 404, and sha256 mismatch no-partial-write cases.
- Standalone install API contract and operator ownership boundaries are documented in `docs/addon-store/SSAP_operator_runbook.md`.
- Addon Store frontend install requests now pass `install_mode` derived from catalog `package_profile` to avoid profile-mode mismatch defaults.
- Frontend tests cover package-profile to install-mode mapping and `standalone_service_install` remediation action rendering.
- Validation checks now include standalone mismatch/success install API tests to confirm mode-selection behavior (`test_catalog_install_rejects_standalone_service_profile_with_guidance`, `test_catalog_install_standalone_service_mode_writes_desired_and_returns_paths`).
- For release publication profile/layout gating, see `docs/distributed_addons/catalog_release_publish_checklist.md`.
- For SAS v1.1 backlog sequencing, see `docs/distributed_addons/sas_v1_1_implementation_plan.md`.

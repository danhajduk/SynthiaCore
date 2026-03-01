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
| Core MQTT info topic | Retained `synthia/core/mqtt/info` publication | Topic used by test publish path; not auto-published on connect/restart heartbeat | Gap |
| Service resolution | Capability-based service resolution endpoint | `/api/services/resolve` implemented (registry + catalog fallback) | Aligned |
| Service tokens | Service-to-service JWT issuance | `/api/auth/service-token` exists but is admin-token gated (no service-principal issuance flow) | Partial |
| Policy grants schema | General limits (`max_requests`, `max_tokens`, `max_cost_cents`, `max_bytes`) | API/persistence/MQTT grant payloads now use the policy limit keys; legacy `max_units`/`burst` inputs are normalized for compatibility | Aligned |
| Revocation topic model | Revocation keyed by both consumer and grant | Core now publishes retained revocations on `consumer_addon_id` and `grant_id` topics, plus legacy `{id}` compatibility topic | Aligned |
| Addon package profiles | Clear embedded-addon vs standalone-service handling | Embedded addon layout enforced; invalid service layout now returns structured diagnostics | Partial |

## Gap-to-Task Mapping
- Task 46: Auto-publish retained `synthia/core/mqtt/info` on connect/restart with sanitized metadata.
- Task 47: Add service-principal token issuance/auth for `/api/auth/service-token`.
- Task 48: Formalize package profiles and install-time validation for `embedded addon` vs `standalone service`.

## Notes
- This baseline is intentionally implementation-focused and is updated as each gap task lands.
- Policy files remain the source of truth for target architecture decisions.

# API Documentation (Structure)

Last Updated: 2026-03-07 15:42 US/Pacific

## Conventions

- API is FastAPI-based and primarily mounted under `/api/*`
- Route groups are assembled in `backend/app/main.py`
- JSON request/response bodies and standard HTTP status codes are used

## Major Route Groups

- `/api/health`
- `/api/addons*` (core addon listing, enablement, registry, install sessions, proxy aliases)
- `/api/admin/*` (session + reload + users/admin registry)
- `/api/system/*` (stats/settings/mqtt/repo/runtime)
- `/api/system/scheduler/*` (jobs/leases/history/queue/debug)
- `/api/auth/*` (service token operations)
- `/api/policy/*` (grants/revocations)
- `/api/telemetry/*` (usage ingestion and stats)
- `/api/services/*` (service resolver)
- `/api/store/*` (schema/catalog/sources/install/update/uninstall/status/diagnostics/audit)

## Auth Requirements (High Level)

- Admin-protected endpoints require admin session/token checks.
- Service-oriented endpoints require service token scope checks.
- Public/read endpoints remain accessible without admin privilege where designed.

Implemented admin-protected runtime endpoints:
- `GET /api/system/addons/runtime`
- `GET /api/system/addons/runtime/{addon_id}`

## Error Format

Implemented:
- Endpoint-specific `detail` payloads for validation and operational diagnostics.
- Store endpoints include structured remediation hints for known failure classes.

## Versioning

Implemented:
- App version appears in FastAPI app metadata (`0.1.0` in backend factory).

Not developed:
- Formal multi-version API versioning strategy across major revisions.

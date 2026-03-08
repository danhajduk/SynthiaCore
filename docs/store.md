# Store and Catalog Documentation

Last Updated: 2026-03-08 10:03 US/Pacific

## Scope

Store subsystem manages catalog sources, schema exposure, install/update/uninstall flows, status and diagnostics.

## Main Modules

- `app/store/router.py`: API contract and orchestration
- `catalog.py`: source refresh/cache and catalog reading
- `lifecycle.py`: install/update/uninstall operations
- `extract.py`: package extraction/validation
- `resolver.py`: compatibility checks
- `audit.py`: store audit persistence
- `standalone_desired.py`, `standalone_paths.py`: standalone runtime intent/path utilities

## Catalog and Sources

Implemented:
- source CRUD and refresh endpoints
- cache metadata per source in runtime store cache paths
- source validate endpoint for schema/version checks

## Install Pipeline

Implemented:
- artifact retrieval and staging
- compatibility checks
- install/update/uninstall endpoint flows
- standalone install mode writes `desired.json` and stages `addon.tgz`
- standalone release manifests may define `runtime_defaults` (`ports`, `bind_localhost`); these defaults are used when `runtime_overrides` are not provided at install time
- standalone runtime overrides support optional `cpu` and `memory` values for desired runtime intent
- standalone uninstall path now performs desired-state stop intent, best-effort compose teardown, and standalone service directory removal
- status/diagnostic endpoints read runtime state and summarize errors
- diagnostics expose standalone retention policy and retained/prunable version lists

## Development Policy

Checksum and signature verification are intentionally disabled during development.
Verification utility paths exist but enforcement is currently bypassed in active store/supervisor flows.

## Not Developed

- Production-grade trust enforcement pipeline (strict verification required mode)
- Full zero-downtime addon rollout orchestration

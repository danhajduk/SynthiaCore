# MQTT Apply and Rollback Pipeline (Phase 1 Foundation)

Last Updated: 2026-03-09 06:37 US/Pacific

## Core Pipeline

Core-side implementation:
- `backend/app/system/mqtt/apply_pipeline.py`

Behavior:
- validate generated artifacts before apply
- stage artifacts before promotion
- preserve backup of live artifacts
- apply runtime reload/restart through runtime boundary
- rollback to backup when runtime remains unhealthy after apply

## Audit Integration

Pipeline emits audit records through:
- `backend/app/system/mqtt/authority_audit.py`

Events include:
- apply success
- validation failure
- rollback on runtime failure

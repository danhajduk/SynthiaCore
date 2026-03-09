# MQTT Startup Reconciliation (Embedded)

Last Updated: 2026-03-09 06:37 US/Pacific

## Implementation

Core startup reconciler:
- `backend/app/system/mqtt/startup_reconcile.py`

Wiring:
- `backend/app/main.py` startup flow invokes reconciler after MQTT manager start.

## Startup Flow

On startup the reconciler:
1. loads Core MQTT authority state
2. compiles ACL artifacts
3. renders broker config artifacts
4. applies staged artifacts through apply pipeline
5. checks runtime readiness through runtime boundary
6. updates setup state (`ready` or `degraded`)
7. publishes retained bootstrap/core info topics when healthy

## Degraded Handling

- Reconcile errors are captured as degraded/error state.
- Audit events are written for startup reconcile outcomes.

# Auth and Identity

## Identity Domains

### Admin Users

Status: Implemented

- Admin sessions support token and credential login flows.
- User CRUD is exposed under admin APIs.

### Service Identity

Status: Implemented

- Service tokens are issued/rotated under `/api/auth/service-token*`.
- Telemetry/services APIs enforce service-token claims where required.

### MQTT Principals

Status: Implemented

- Core tracks principal state and lifecycle for addon/system/generic identities.
- Principal actions and effective-access inspections are admin-controlled.

## Roles and Boundaries

Status: Implemented

- `admin`: privileged control-plane and lifecycle writes.
- `service`: scoped service-to-core operations.
- guest/read-only surfaces remain limited to non-privileged endpoints.

## Generic Users vs System Principals

Status: Implemented

- Generic users can be lifecycle-managed and scoped to approved topic access.
- System/addon principals carry platform-owned responsibilities and reserved-family access as needed.

## MQTT Identity Model

Status: Implemented (Phase 2 basis), Partial (future expansion)

- Effective-access model compiles principal permissions into deterministic ACL outputs.
- Generic users are blocked from reserved platform families.
- Future identity federation and advanced role policy inheritance are planned.

## Archived Legacy Behavior

Status: Archived Legacy

- Earlier split identity guidance from `auth-and-users.md` and MQTT authority design notes has been consolidated here.

## See Also

- [MQTT Platform](../mqtt/mqtt-platform.md)
- [Core Platform](./core-platform.md)
- [API Reference](./api-reference.md)
- [Data and State](./data-and-state.md)

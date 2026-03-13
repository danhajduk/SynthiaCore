# MQTT Docs

This folder contains the messaging and notification documentation for the Core-managed MQTT subsystem.

## Included Docs

- [mqtt-platform.md](./mqtt-platform.md)
  Authority, setup, runtime, and policy behavior for the MQTT platform.
- [notifications.md](./notifications.md)
  Notification schema, internal/external topic families, and bridge behavior.

## Code Boundary

Status: Implemented

- MQTT runtime and API code live under `backend/app/system/mqtt/`.
- Shared notification helpers live under `backend/app/core/`.

## See Also

- [../fastapi/core-platform.md](../fastapi/core-platform.md)
- [../supervisor/runtime-and-supervision.md](../supervisor/runtime-and-supervision.md)

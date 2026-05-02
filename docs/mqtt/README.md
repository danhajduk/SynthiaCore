# MQTT Docs

This folder contains the messaging and notification documentation for the Hexe Core-managed MQTT subsystem.

The active MQTT namespace is `hexe/...`.

## Included Docs

- [mqtt-platform.md](./mqtt-platform.md)
  Authority, setup, runtime, and policy behavior for the MQTT platform.
- [topics.md](./topics.md)
  Canonical MQTT topic families and scope rules derived from runtime code.
- [notifications.md](./notifications.md)
  Notification schema, internal/external topic families, and bridge behavior.
- [node-domain-event-promotion.md](./node-domain-event-promotion.md)
  Proposed Core bridge for validating node-originated domain events and promoting them to `hexe/events/#`.
- [../nodes/node-notification-mqtt-contract.md](../nodes/node-notification-mqtt-contract.md)
  MQTT-only node notification proxy contract and request/result payloads.

## Code Boundary

Status: Implemented

- MQTT runtime and API code live under `backend/app/system/mqtt/`.
- Shared notification helpers live under `backend/app/core/`.

## See Also

- [../fastapi/core-platform.md](../fastapi/core-platform.md)
- [../supervisor/runtime-and-supervision.md](../supervisor/runtime-and-supervision.md)

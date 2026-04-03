# Node Notification MQTT Contract

Status: Implemented

## Purpose

Defines the MQTT-only protocol a trusted node can use to ask Core to emit a user-facing notification.

Core acts as the notification authority:

- nodes publish a notification proxy request under their own node-scoped MQTT namespace
- Core validates the request against the node MQTT identity and node principal state
- Core rewrites the authoritative notification source to the node identity
- Core publishes the request into the canonical internal notification bus
- Core may bridge the resulting notification to external targets such as `hexe-notify/<target>`
- Core publishes an acceptance or rejection result back to the node over MQTT

## Topics

Request topic:

- `hexe/nodes/<node_id>/notify/request`

Result topic:

- `hexe/nodes/<node_id>/notify/result`

The node principal issued during trust activation already owns `hexe/nodes/<node_id>/#`, so no additional MQTT identity is required for this protocol.

## Request Contract

Status: Implemented

Request payload schema:

- [Node Notification Request JSON Schema](../json_schema/node_notification_request.schema.json)

Current required fields:

- `kind`
- `targets`
- at least one payload section: `content`, `event`, `state`, or `data`

Current optional fields:

- `schema_version`
- `request_id`
- `created_at`
- `node_id`
- `delivery`
- `retain`
- `source`
- `content`
- `event`
- `state`
- `data`

`kind` values:

- `popup`
- `event`
- `state`

`delivery.urgency` values:

- `info`
- `error`
- `notification`
- `urgent`
- `actions_needed`

`retain` behavior:

- allowed only for `kind=state`
- rejected for `popup` and `event`

## Source Rewriting Rules

Status: Implemented

Core does not trust the node to provide the authoritative notification identity.

Core rewrites the outgoing internal notification source to:

- `source.kind = node`
- `source.id = <node_id from MQTT topic>`

Core currently preserves these optional source hints from the request when present:

- `source.component`
- `source.label`
- `source.metadata`

Core also injects these metadata fields:

- `node_principal_id`
- `request_id`

## Request Validation Rules

Status: Implemented

Core rejects the request when:

- the MQTT message is retained
- the payload does not match the request schema
- `node_id` is present in the payload and does not match the `<node_id>` topic segment
- the node principal does not exist
- the node principal is revoked or expired
- the downstream internal publish fails

Current rejection error strings include:

- `retained_requests_not_supported`
- `notification_request_invalid`
- `node_id_topic_mismatch`
- `node_principal_unavailable`
- `notification_publish_failed`

## Internal Publish Mapping

Status: Implemented

Core maps the request to the canonical internal notification bus like this:

- `kind=popup` -> `hexe/notify/internal/popup`
- `kind=event` -> `hexe/notify/internal/event`
- `kind=state` -> `hexe/notify/internal/state`

After internal publish, the existing Core bridge and local consumer continue to apply the normal notification rules:

- local popup filtering and target matching
- TTL expiry handling
- dedupe handling
- external forwarding based on `targets.external`

## External Target Behavior

Status: Partially implemented

The proxy request contract is generic and can ask for external targets through `targets.external`.

Current verified Core bridge support:

- `ha`

This means a node can request:

- `targets.external = ["ha"]`

and Core will publish the transformed external payload to:

- `hexe-notify/ha`

Additional external targets are not currently verified from repository state.

## Result Contract

Status: Implemented

Result payload schema:

- [Node Notification Result JSON Schema](../json_schema/node_notification_result.schema.json)

Current result fields:

- `request_id`
- `node_id`
- `status`
- `accepted`
- `created_at`
- `notification_id` when accepted
- `internal_topic` when accepted
- `error` when rejected
- `requested_external_targets`

`status` values:

- `accepted`
- `rejected`

## Example Request

```json
{
  "schema_version": 1,
  "request_id": "motion-front-001",
  "kind": "event",
  "targets": {
    "external": ["ha"]
  },
  "delivery": {
    "severity": "warning",
    "priority": "high",
    "urgency": "actions_needed",
    "dedupe_key": "front-door-motion"
  },
  "source": {
    "component": "front_camera",
    "label": "Front Door Camera",
    "metadata": {
      "camera_id": "front-door"
    }
  },
  "content": {
    "title": "Front Door Motion",
    "message": "Motion detected at the front door."
  },
  "event": {
    "event_type": "motion_detected",
    "summary": "Front door motion detected"
  },
  "data": {
    "confidence": 0.98
  }
}
```

Publish that JSON to:

- `hexe/nodes/<node_id>/notify/request`

## Example Accepted Result

```json
{
  "schema_version": 1,
  "request_id": "motion-front-001",
  "node_id": "node-123",
  "status": "accepted",
  "accepted": true,
  "created_at": "2026-04-03T19:00:00+00:00",
  "notification_id": "f2b8d55d-4d55-49a1-a5db-7f6765df5d8d",
  "internal_topic": "hexe/notify/internal/event",
  "requested_external_targets": ["ha"]
}
```

## Example Rejected Result

```json
{
  "schema_version": 1,
  "request_id": "motion-front-001",
  "node_id": "node-123",
  "status": "rejected",
  "accepted": false,
  "created_at": "2026-04-03T19:00:02+00:00",
  "error": "node_id_topic_mismatch",
  "requested_external_targets": ["ha"]
}
```

## Verified Code Anchors

- `backend/app/core/notifications.py`
- `backend/app/core/notification_proxy.py`
- `backend/app/core/notification_publisher.py`
- `backend/app/core/notification_bridge.py`
- `backend/app/main.py`

## See Also

- [Notifications Bus](../mqtt/notifications.md)
- [MQTT Platform](../mqtt/mqtt-platform.md)
- [Node Trust Activation Payload Contract](./node-trust-activation-payload-contract.md)

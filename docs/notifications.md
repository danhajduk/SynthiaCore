# Notifications Bus

## Purpose

Status: Implemented

Synthia Core exposes a canonical MQTT-backed notification bus for internal producers, local consumers, and bridge-owned external integrations.

Code anchors:
- `backend/app/core/notifications.py`
- `backend/app/core/notification_publisher.py`
- `backend/app/core/notification_producer.py`
- `backend/app/core/notification_consumer.py`
- `backend/app/core/notification_bridge.py`

## Topic Model

Status: Implemented

Internal canonical topics:
- `synthia/notify/internal/popup`
- `synthia/notify/internal/event`
- `synthia/notify/internal/state`

External bridge-owned topics:
- `synthia/notify/external/<target>`
- currently implemented target: `synthia/notify/external/ha`

Producer rule:
- Core producers publish only to internal topics through the shared publisher.
- External topics are owned by bridge services and must not be published directly by normal producers.

## Schema

Status: Implemented

Canonical message model:
- `NotificationMessage`
- `NotificationSource`
- `NotificationTargets`
- `NotificationDelivery`
- `NotificationContent`
- `NotificationEvent`
- `NotificationState`

Required sections:
- `source`
- `targets`
- at least one payload section: `content`, `event`, `state`, or `data`

Optional sections:
- `delivery`
- `content`
- `event`
- `state`
- `data`

Validation rules:
- `targets` must include at least one non-empty target list or `broadcast=true`
- empty `event` objects are rejected
- empty `state` objects are rejected
- empty payload objects should be omitted rather than sent as `{}` placeholders

## Routing Rules

Status: Implemented

Internal topic purpose:
- `popup` is for local popup-capable notifications
- `event` is for transient event/alert style notifications
- `state` is for current status style notifications

External topic purpose:
- external topics carry simplified bridge-owned payloads for integration consumers
- external payloads are intentionally smaller than the internal canonical schema

Target matching behavior:
- local desktop consumer accepts `broadcast=true`
- local desktop consumer also accepts matching `targets.users`, `targets.hosts`, or `targets.sessions`
- bridge forwards only when `targets.external` contains supported values

Delivery channel behavior:
- `delivery.channels` are routing hints for consumers and bridges
- they are not hard execution commands
- consumers may still apply local filters such as popup support, expiry, and target matching

## Retain, TTL, and Dedupe

Status: Implemented

Retain rules:
- popup notifications are published non-retained
- event notifications are published non-retained
- state notifications are published non-retained by default and retained only when explicitly requested
- current HA bridge output is published non-retained

TTL rules:
- `delivery.ttl_seconds` is optional
- consumers and bridges drop expired messages using `created_at + ttl_seconds`
- messages without `ttl_seconds` do not expire automatically

Dedupe rules:
- `delivery.dedupe_key` is optional
- local desktop consumer deduplicates repeated popup-capable notifications by `dedupe_key`
- bridge forwards `dedupe_key` to HA as `tag` when present

## Severity and Priority

Status: Implemented

Severity values:
- `info`
- `success`
- `warning`
- `error`
- `critical`

Priority values:
- `low`
- `normal`
- `high`
- `urgent`

Current conventions:
- severity describes operator importance
- priority is available for future consumer-specific handling
- local desktop consumer maps severity to `notify-send` urgency

## Home Assistant Contract

Status: Implemented

External topic:
- `synthia/notify/external/ha`

Current payload fields:
- `title`: user-facing title
- `message`: simplified message body
- `severity`: canonical severity string
- `tag`: dedupe key when present
- `kind`: `popup`, `event`, or `state`
- `created_at`: canonical message timestamp
- `source.kind`: source kind
- `source.id`: source identifier
- `source.component`: source component when present

Producer and bridge responsibilities:
- producers emit canonical internal notifications only
- bridge transforms internal notifications to simplified HA payloads
- bridge forwards only supported external targets and currently supports `ha`

Example popup-originated external payload:

```json
{
  "title": "Synthia Core Ready",
  "message": "Core startup completed and notification publishing is active.\nStartup popup smoke test",
  "severity": "success",
  "tag": "core-startup-popup",
  "kind": "popup",
  "created_at": "2026-03-12T17:32:00+00:00",
  "source": {
    "kind": "core",
    "id": "synthia-core",
    "component": "startup"
  }
}
```

Example event-originated external payload:

```json
{
  "title": "Synthia Debug Alert",
  "message": "Developer-triggered alert for HA/mobile relay.\nDebug external alert",
  "severity": "warning",
  "tag": "dev-event-ha",
  "kind": "event",
  "created_at": "2026-03-12T17:40:00+00:00",
  "source": {
    "kind": "core",
    "id": "synthia-core",
    "component": "debug"
  }
}
```

Example state-originated external payload:

```json
{
  "title": "Core runtime ready",
  "message": "Core runtime state published after startup.\nready",
  "severity": "success",
  "tag": "core-startup-state",
  "kind": "state",
  "created_at": "2026-03-12T17:32:00+00:00",
  "source": {
    "kind": "core",
    "id": "synthia-core",
    "component": "startup"
  }
}
```

Recommended HA automation/mobile mapping:
- use `title` for mobile notification title
- use `message` for mobile notification body
- map `tag` into HA/mobile notification `tag` or dedupe field when available
- include `severity`, `kind`, and `source.*` as mobile `data` fields for routing or styling

## Developer Test Hook

Status: Implemented

Dev-only endpoint:
- `POST /api/system/mqtt/debug/notifications/test-flow`

Access and gating:
- requires admin authentication via `X-Admin-Token`
- endpoint is hidden behind `NOTIFICATION_DEBUG_ENABLED=true`

Current emitted flow:
- one popup notification targeted to the local host and current user
- one event notification targeted to `external=["ha"]` for bridge forwarding
- one retained state notification

Expected observable results:
- local desktop popup appears when the local consumer target matches the current user/host/session
- bridge publishes transformed event payload to `synthia/notify/external/ha`
- logs show publish, bridge, and consumer decisions

## See Also

- [MQTT Platform](./mqtt-platform.md)
- [Core Platform](./core-platform.md)
- [API Reference](./api-reference.md)
- [Development Guide](./development-guide.md)

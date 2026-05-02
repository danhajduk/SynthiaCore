# Node Domain Event Promotion

Status: Proposed

## Purpose

Trusted nodes need a way to publish machine-actionable domain events that other nodes and Core components can consume without knowing every producer node id.

Nodes already own `hexe/nodes/<node_id>/#`, while `hexe/events/#` is a reserved Core/platform namespace. This document defines the proposed bridge between those two scopes:

- nodes publish raw domain events under their own namespace
- Core validates, rate-limits, redacts, deduplicates, and promotes accepted events
- consumers subscribe to Core-owned shared event topics

## Topic Model

Node-originated input topic:

```text
hexe/nodes/<node_id>/events/<domain>/<event_name>
```

Core-promoted source-preserving topic:

```text
hexe/events/nodes/<node_id>/<domain>/<event_name>
```

Core-promoted domain topic:

```text
hexe/events/<domain>/<event_name>
```

Example delivery flow:

```text
hexe/nodes/email-node-1/events/delivery/window/upserted
hexe/events/nodes/email-node-1/delivery/window/upserted
hexe/events/delivery/window/upserted
```

Consumers such as a vision node should subscribe to the Core-promoted domain topic, for example:

```text
hexe/events/delivery/#
```

They should not need to know the Email node id.

## ACL Policy

Default trusted node ACLs remain unchanged:

- publish: `hexe/nodes/<node_id>/#`
- subscribe:
  - `hexe/bootstrap/core`
  - `hexe/nodes/<node_id>/#`

Core owns `hexe/events/#`.

Trusted nodes must not receive broad publish access to `hexe/events/#` by default. Direct reserved publish access may be granted only for a narrow topic and only with explicit reserved approval.

## Core Bridge Responsibilities

Core should run a node domain event promoter that subscribes to:

```text
hexe/nodes/+/events/#
```

For each received message, Core should:

1. Extract `<node_id>` from the topic.
2. Verify the MQTT principal is an active `synthia_node` linked to that node id.
3. Reject retained messages.
4. Validate the payload against the node-originated event schema.
5. Verify payload `source.node_id` matches the topic node id.
6. Enforce privacy policy and redact if needed.
7. Enforce noisy-node policy.
8. Deduplicate using event id, source topic, and optional subject ids.
9. Publish accepted events to the source-preserving and domain topics.
10. Record accept/reject/limit decisions in Core observability.

## Required Schemas

Node-originated event schema:

- `HexeEmail/docs/schemas/email-node-domain-event.schema.json`

Core-promoted event schema:

- `docs/json_schema/core_promoted_node_domain_event.schema.json`

Core should treat the node-originated schema as the validation contract for Email-node input events. The promoted schema is the contract for events republished under `hexe/events/#`.

## Event Payload Policy

Node-originated events must be small, structured, and safe for a shared automation bus.

Allowed:

- stable ids: `message_id`, `record_id`, `transaction_id`, `entity_ids`
- classification family and confidence
- vendor, carrier, sender domain
- delivery window timestamps
- high-level status and review-needed flags
- redacted domain metadata needed for automation

Forbidden:

- raw email body
- OAuth tokens, refresh tokens, API keys, session cookies
- verification codes
- full payment numbers or bank account numbers
- full street addresses unless Core has an explicit address-sharing policy
- attachments or large HTML payloads

Core may reject or redact events that violate policy.

## Noisy Node Policy

Core should track node-domain event behavior per node and per topic family.

Recommended initial thresholds:

- `watch`: more than 60 events/minute or more than 10 invalid events in 10 minutes
- `limited`: more than 180 events/minute, more than 50 invalid events in 10 minutes, or more than 1 MiB/minute of event payloads
- `blocked`: sustained limited state for 5 minutes, repeated malformed bursts after limiting, or suspected secret/raw-body leakage

Recommended enforcement:

- `normal`: accept valid events
- `watch`: accept valid events and record diagnostics
- `limited`: drop or sample non-critical events, continue accepting safety-critical events if valid
- `blocked`: reject all node-domain event promotions until operator review or automated cooldown clears the state

Core should include noisy-node decisions in observability records and expose recent decisions through an operator API.

## Delivery Example

Email node receives a DoorDash delivery email and publishes:

```text
hexe/nodes/email-node-1/events/delivery/window/upserted
```

Core promotes it to:

```text
hexe/events/delivery/window/upserted
```

A vision node subscribes to:

```text
hexe/events/delivery/#
```

The vision node can then monitor the doorbell camera near the delivery window and publish its own observation under:

```text
hexe/nodes/vision-node-1/events/delivery/status_changed
```

Core promotes that observation back into the shared delivery event stream.

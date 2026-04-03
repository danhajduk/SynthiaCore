# Phase 2 Full Namespace Migration To Hexe

Status: Implemented
Last updated: 2026-03-20

## Purpose

Phase 2 completes the active MQTT namespace cutover from `synthia/...` to `hexe/...`.

This phase removes the old runtime topic root from active Core code, active tests, and active operator/node/addon documentation. After this phase, `hexe/...` is the only canonical runtime namespace.

## Scope

This migration covers:

- MQTT topic helpers and classifiers
- retained bootstrap publication
- notification bus topics
- node, addon, service, policy, event, runtime, and supervisor topic families
- Core publish/subscribe defaults
- active docs and examples
- automated tests for active MQTT behavior

This migration does not rewrite historical phase reports or archival documentation except where a migration note is needed for clarity.

## Canonical Topic Families

The active platform root is now `hexe/`.

Canonical active examples:

- `hexe/bootstrap/core`
- `hexe/core/mqtt/info`
- `hexe/notify/internal/popup`
- `hexe/notify/internal/event`
- `hexe/notify/internal/state`
- `hexe-notify/<target>`
- `hexe/addons/<addon_id>/...`
- `hexe/nodes/<node_id>/...`
- `hexe/services/<service>/catalog`
- `hexe/policy/grants/<id>`
- `hexe/policy/revocations/<id>`
- `hexe/events/<event_type>`

## Required Runtime Changes

Phase 2 required these runtime updates:

- make the MQTT topic helper layer emit `hexe/...` only
- update reserved-family classification to treat `hexe/` as the internal platform root
- migrate bootstrap publication from `synthia/bootstrap/core` to `hexe/bootstrap/core`
- migrate notification publish/subscribe paths to `hexe/notify/...`
- migrate retained grant/revocation publication to `hexe/policy/...`
- migrate node and addon runtime topic defaults to `hexe/nodes/...` and `hexe/addons/...`
- update Core MQTT subscriptions and runtime classifiers to expect `hexe/...`

## Impacted Components

The following active component groups must align to the new namespace:

- Core backend MQTT manager and authority logic
- notification producer, consumer, and bridge flows
- node onboarding/bootstrap discovery clients
- addon announce/health publishers
- policy grant/revocation consumers
- internal node budget policy/grant consumers

## Risks

Main migration risks:

- external clients still publishing or subscribing to `synthia/...`
- retained broker data under old paths causing confusion during rollout
- stale docs/examples encouraging legacy topic usage
- tests still asserting the old namespace and masking real regressions

## Verification Checklist

- active backend runtime emits only `hexe/...` MQTT topics
- bootstrap publication is retained on `hexe/bootstrap/core`
- retained grants and revocations are published on `hexe/policy/...`
- notification internal/external topics use `hexe/notify/...`
- topic-family helpers classify `hexe/...` correctly and treat non-`hexe/` paths as external
- active tests assert `hexe/...` only
- active docs/examples no longer describe `synthia/...` as the live namespace

## Connected Component Update Checklist

Connected nodes, addons, and external integrations should be updated to:

- subscribe to `hexe/bootstrap/core` for bootstrap discovery
- use `hexe/addons/...` and `hexe/nodes/...` topic families
- consume policy material from `hexe/policy/...`
- consume notification topics from `hexe/notify/...`
- stop relying on `synthia/...` runtime topic literals

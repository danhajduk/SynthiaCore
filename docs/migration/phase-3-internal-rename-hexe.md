# Phase 3 Internal Rename Cleanup To Hexe

Status: In progress
Last updated: 2026-03-20

## Scope

Phase 3 cleans up active internal and product-facing naming that still uses legacy `Synthia` branding after:

- Phase 0 public-facing rebrand
- Phase 1 naming abstraction
- Phase 2 MQTT namespace migration

This phase focuses on active implementation code, active docs, tests, scripts, and operator-facing metadata.

## What Counts As An Internal Identifier

For this phase, internal identifiers include:

- helper names and constant names
- product-facing package metadata
- browser event names used inside the app
- notification source ids used for internal UI/bridge behavior
- operator-facing script output
- service descriptions and display labels

This phase does not automatically rename every legacy technical contract.

## Allowed Renames

Safe renames in this phase include:

- product-facing text from `Synthia` to `Hexe`
- frontend package/app metadata
- UI/browser event ids that are internal to this app
- active notification/debug source ids used for internal flows
- active docs that still describe `Synthia` as current branding
- test fixtures that only mirror the renamed active behavior

## Disallowed Or Deferred Renames

These should be deferred or treated as compatibility-sensitive unless explicitly migrated:

- API route paths
- env var names prefixed with `SYNTHIA_`
- systemd unit filenames like `synthia-backend.service`
- token audiences such as `synthia-core`
- repo/module/package paths like `backend/synthia_supervisor`
- persisted runtime state under `backend/var/`

## Risks

Main risks in this phase:

- breaking compatibility-sensitive integrations by renaming technical contracts too aggressively
- creating branding drift where docs claim one thing and runtime behavior exposes another
- renaming machine-parsed identifiers that external tools still depend on

## Validation Requirements

- active product-facing strings should prefer Hexe naming
- active docs should not describe `Synthia` as the current platform brand
- active tests should match the renamed product-facing behavior
- remaining legacy identifiers must be intentional and documented

## Rollback Notes

Rollback should target product-facing rename changes only.

Do not roll back compatibility-sensitive identifiers unless a specific contract migration also rolls back with them.

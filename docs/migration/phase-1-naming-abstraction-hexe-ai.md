# Phase 1 Naming Abstraction: Hexe AI

Status: Implemented
Last updated: 2026-03-20 12:05

## Purpose

Phase 1 introduces the canonical naming abstraction layer that lets the platform present itself as `Hexe AI` externally while continuing to tolerate legacy internal `synthia` identifiers where compatibility requires them.

This phase builds on the public-facing Phase 0 rebrand by replacing ad-hoc display strings with shared backend and frontend naming helpers.

## Scope

Phase 1 covers:

- canonical platform identity modeling
- component display names for Core, Supervisor, Nodes, Addons, and Docs
- backend naming helper usage
- frontend branding provider usage
- centralized compatibility messaging for retained legacy naming
- code-verified rules for how product-facing naming should be consumed

Phase 1 does not rename:

- MQTT topic roots
- API route paths
- internal package/module paths
- protocol payload keys
- retained runtime identifiers such as `synthia-core`

## Relationship To Phase 0

Phase 0 changed the public-facing names on major surfaces.

Phase 1 makes those names systematic by adding:

- a canonical identity model in backend code
- a backend naming service/helper layer
- a frontend provider that consumes `/api/system/platform`
- centralized compatibility text for legacy internal naming

## Design Rules

Display identity and internal identifiers are separate concerns.

Allowed:

- display `Hexe AI`, `Hexe Core`, `Hexe Supervisor`, `Hexe Nodes`, `Hexe Addons`, and `Hexe Docs`
- show a compatibility note when an operator needs to understand why `synthia` still appears internally
- derive UI and backend labels from the shared identity model

Forbidden:

- adding new hardcoded product-facing `Synthia` strings when a helper exists
- adding new hardcoded product-facing `Hexe` strings when a helper exists
- inferring public labels from MQTT topic roots or package/module names
- renaming protocol literals during this abstraction phase

## Backend Consumption Rules

Backend product-facing code should use:

- `PlatformIdentity` for canonical serialized identity data
- `PlatformNamingService` for display labels and compatibility note generation

Current canonical source:

- [backend/app/system/platform_identity.py](/home/dan/Projects/Hexe/backend/app/system/platform_identity.py)

Canonical API exposure:

- `GET /api/system/platform`

## Frontend Consumption Rules

Frontend product-facing code should use:

- `PlatformBrandingProvider`
- `usePlatformBranding()`
- `usePlatformLabel()`
- `useLegacyCompatibilityNote()`

Current canonical source:

- [frontend/src/core/branding.tsx](/home/dan/Projects/Hexe/frontend/src/core/branding.tsx)

## Current Identity Model

The canonical identity model currently includes:

- `platform_name`
- `platform_short`
- `platform_domain`
- `core_name`
- `supervisor_name`
- `nodes_name`
- `addons_name`
- `docs_name`
- `legacy_internal_namespace`
- `legacy_compatibility_note`

## Standard Usage Rules For New Code

1. Do not hardcode `Synthia` or `Hexe` in product-facing backend/frontend code when the naming helper/provider can supply the label.
2. Use `/api/system/platform` as the frontend source of truth for component display names.
3. Keep protocol and compatibility identifiers explicit and separate from display labels.
4. If a screen or API needs to explain retained internal naming, use the canonical compatibility note instead of inventing new copy.
5. Archived material may retain legacy naming when it is documenting historical or compatibility behavior.

## See Also

- [Phase 0 Cosmetic Rebrand: Hexe AI](./phase-0-cosmetic-rebrand-hexe-ai.md)
- [Phase 1 Completion Report](./phase-1-completion-report.md)
- [Phase 1 Branding Audit](./phase-1-branding-audit.md)

# Node Capability Taxonomy

Status: Implemented

This document defines the canonical node capability taxonomy exposed across node APIs, node registry payloads, capability profile records, and the operator UI.

## Source Of Truth

- `backend/app/system/onboarding/capability_taxonomy.py`
- `backend/app/system/onboarding/registry_view.py`
- `backend/app/system/onboarding/capability_profiles.py`
- `backend/app/api/system.py`
- `backend/app/nodes/models.py`

## Taxonomy Version

- `version: "1"`

## Stable Categories

The taxonomy publishes the same ordered categories in every response:

### `task_families`

- Label: `Task families`
- Source: `declared_task_families[]` / `declared_capabilities[]`
- Meaning: workload families the node declares it can perform

### `provider_access`

- Label: `Provider access`
- Source: `enabled_providers[]`
- Meaning: provider identifiers the node has enabled for active use

### `provider_models`

- Label: `Provider models`
- Source: normalized `provider_intelligence[].available_models[]`
- Meaning: concrete provider model identifiers currently reported for routing and inspection

Each category includes:

- `category_id`
- `label`
- `items`
- `item_count`

## Activation Semantics

The taxonomy also publishes a stable activation summary under `activation`.

### Stages

- `not_declared`: no capability declaration has been accepted or stored
- `declaration_received`: declaration metadata exists but no accepted profile is active yet
- `profile_accepted`: Core accepted the declaration and issued a capability profile
- `governance_issued`: governance has been issued for the active capability profile, but the node is not yet operational
- `operational`: capability declaration, governance, and readiness conditions are all satisfied

### Activation Flags

- `declaration_received`
- `profile_accepted`
- `governance_issued`
- `operational`

## Reuse Rules

- API responses should reuse the existing declaration/profile/provider fields and add taxonomy as a derived summary.
- UI surfaces should prefer the taxonomy stage and category labels for presentation rather than inventing alternate wording.
- Future capability categories should extend taxonomy versioning instead of renaming existing category identifiers.

# Node Registry Domain

Status: Implemented

This document defines the canonical node registry domain introduced for the Nodes layer.

## Source Of Truth

- `backend/app/nodes/models.py`
- `backend/app/nodes/registry.py`
- `backend/app/nodes/service.py`

## Canonical Models

### NodeRecord

- `node_id`
- `node_name`
- `node_type`
- `requested_node_type`
- `node_software_version`
- `approved_by_user_id`
- `approved_at`
- `source_onboarding_session_id`
- `created_at`
- `updated_at`
- `provider_intelligence`
- `capabilities`
- `status`

### NodeCapabilitySummary

- `declared_capabilities`
- `enabled_providers`
- `capability_profile_id`
- `capability_status`
- `capability_declaration_version`
- `capability_declaration_timestamp`
- `taxonomy`

### NodeCapabilityTaxonomySummary

- `version`
- `categories`
- `activation`

Stable category identifiers:

- `task_families`
- `provider_access`
- `provider_models`

Stable activation stages:

- `not_declared`
- `declaration_received`
- `profile_accepted`
- `governance_issued`
- `operational`

### NodeStatusSummary

- `trust_status`
- `registry_state`
- `governance_sync_status`
- `operational_ready`
- `active_governance_version`
- `governance_last_issued_at`
- `governance_last_refresh_request_at`

## Registry Abstraction

`NodeRegistry` is the canonical list/lookup abstraction for the Nodes domain.

Current implementation:

- reuses `NodeRegistrationsStore` as the persisted source
- reuses governance status service data when available
- normalizes the result into `NodeRecord`

This keeps the current registration schema as the storage source while making the Nodes layer own the canonical API-facing registry model.

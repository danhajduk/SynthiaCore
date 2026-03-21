# Node Service Resolution And Budgeting

Status: Implemented
Last Updated: 2026-03-20 09:20

## Purpose

Defines the Core-side contract that lets a trusted node ask:

1. who can satisfy this task family
2. what budget grant applies
3. how to obtain a short-lived authorization token for the selected service

This contract explicitly reuses existing Core subsystems rather than creating new policy channels:

- service catalog storage and resolution
- service-token issuance primitives
- node governance
- node budget policy and derived grants
- periodic node usage summaries
- retained MQTT policy topics

## Canonical Rules

### Task Family Versus Task Context

Task families remain semantic and stable.

Examples:

- `task.summarization`
- `task.classification`

Task context belongs in metadata, not in the canonical task-family id.

Examples:

- allowed: `task.summarization` with `task_context.content_type=email`
- rejected: `task.summarization.email`

### Taxonomy Separation

Core keeps these as distinct concepts:

- task family
- provider
- model
- grant/budget

The resolution flow combines them, but it does not collapse them into one identifier.

### Core Resolves, Node Executes

Core remains:

- trust authority
- governance authority
- service discovery authority
- policy and budget authority
- short-lived service-token issuer

Node remains:

- execution client
- local prompt and service orchestration owner
- local grant-enforcement point
- usage reporter

Core does not proxy execution requests in the hot path.

## Existing Building Blocks Reused

- generic service catalog storage: [backend/app/system/services/store.py](/home/dan/Projects/Hexe/backend/app/system/services/store.py)
- generic service registration and resolution: [backend/app/system/services/router.py](/home/dan/Projects/Hexe/backend/app/system/services/router.py)
- service-token issuance primitives: [backend/app/system/auth/router.py](/home/dan/Projects/Hexe/backend/app/system/auth/router.py)
- node governance and routing-policy constraints: [backend/app/system/onboarding/governance.py](/home/dan/Projects/Hexe/backend/app/system/onboarding/governance.py)
- node budget policy and derived grants: [backend/app/system/onboarding/node_budgeting.py](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py)
- node-facing budget policy fetch/refresh: [backend/app/api/system.py](/home/dan/Projects/Hexe/backend/app/api/system.py)

## Service Catalog Contract

The service catalog remains the source of service/provider candidates.

`POST /api/services/register` now supports additional optional metadata used by node resolution:

- `service_id`
- `provider`
- `models`
- `declared_capacity`
- `auth_modes`
- `required_scopes`

Retained MQTT service catalogs are still accepted through the existing MQTT service-catalog ingestion path. Core persists those payloads in the same service catalog store.

## Node Resolution Contract

### Route

- `POST /api/system/nodes/services/resolve`
- Auth: `X-Node-Trust-Token`

### Request

```json
{
  "node_id": "node-abc123",
  "task_family": "task.summarization",
  "task_context": {
    "content_type": "email"
  },
  "preferred_provider": "openai",
  "preferred_model": "gpt-4o-mini"
}
```

### Response

```json
{
  "ok": true,
  "node_id": "node-abc123",
  "task_family": "task.summarization",
  "task_context": {
    "content_type": "email"
  },
  "selected_service_id": "summary-service",
  "candidates": [
    {
      "service_id": "summary-service",
      "service_type": "ai-inference",
      "provider": "openai",
      "models_allowed": ["gpt-4o-mini"],
      "required_scopes": ["service.execute:task.summarization"],
      "auth_mode": "service_token",
      "grant_id": "grant:node-abc123:node",
      "resolution_mode": "catalog_governance_budget",
      "health_status": "healthy",
      "declared_capacity": {
        "limits": {
          "max_tokens": 1000000
        }
      },
      "budget_view": {
        "status": "active",
        "grant_id": "grant:node-abc123:node",
        "admissible": true
      }
    }
  ]
}
```

### Resolution Inputs

Core combines:

- trusted node identity
- accepted capability profile
- governance `routing_policy_constraints`
- service catalog candidates
- current budget-policy and derived grants

### Resolution Filters

Candidates are filtered by:

- matching `task_family` in service capabilities
- service health
- governance allowed providers
- governance allowed models
- preferred provider/model when requested
- admissible current budget grant

### Governance Freshness Gate

Resolution and authorization are blocked when the node governance freshness state is `outdated`.

Current rule:

- `critical` after 6 hours without governance refresh activity: warn only
- `outdated` after 24 hours without governance refresh activity: block new `resolve` and `authorize` requests with `409 node_governance_outdated`

Recovery path:

- node refreshes governance through `/api/system/nodes/governance/current` or `/api/system/nodes/governance/refresh`
- once freshness returns to `fresh`, service resolution and authorization resume normally

## Effective Budget Resolution

Core now computes an effective budget view for:

- `node_id`
- `task_family`
- `provider`
- `model_id`

The current helper reuses the existing node budget grant system instead of creating a second grant protocol.

Current behavior:

- provider-specific grants are preferred when present
- node-wide grants remain the fallback
- existing provider-allocation hard-slice rules are respected
- remaining `max_requests`, `max_tokens`, and `max_cost_cents` are computed from periodic usage summaries already stored for the matching grant

## Node Authorization Contract

### Route

- `POST /api/system/nodes/services/authorize`
- Auth: `X-Node-Trust-Token`

### Request

```json
{
  "node_id": "node-abc123",
  "task_family": "task.summarization",
  "task_context": {
    "content_type": "email"
  },
  "service_id": "summary-service",
  "provider": "openai",
  "model_id": "gpt-4o-mini"
}
```

### Response

```json
{
  "ok": true,
  "node_id": "node-abc123",
  "service_id": "summary-service",
  "provider": "openai",
  "model_id": "gpt-4o-mini",
  "grant_id": "grant:node-abc123:node",
  "required_scopes": ["service.execute:task.summarization"],
  "expires_at": "2026-03-20T08:30:00+00:00",
  "token": "<jwt>",
  "claims": {
    "sub": "node-abc123",
    "aud": "summary-service",
    "scp": ["service.execute:task.summarization"]
  }
}
```

### Authorization Rules

Authorization reuses the existing Core service-token issuer primitives but gates issuance through:

- trusted node auth
- current governance
- current resolution result
- admissible effective budget view

If no candidate or no admissible grant exists, authorization is denied.

## Usage Reporting

Nodes continue to report usage through the existing budget usage-summary path:

- `POST /api/system/nodes/budgets/usage-summary`

Current implementation now supports tagging summaries with:

- `provider`
- `model_id`
- `task_family`

Admin usage-report reads can filter by provider and task family and now include rollups by:

- service
- provider
- task family

## Policy Distribution

This flow reuses the current policy distribution model:

- governance remains the canonical Core-to-node policy carrier
- budget policy remains embedded in governance and readable directly through budget-policy routes
- retained grant/revocation topics remain under `hexe/policy/...`

No new parallel policy transport was introduced for this feature.

## Failure Model

If Core is temporarily unavailable:

- node continues using cached governance and budget policy according to the existing fallback rules
- no new authorization tokens can be minted until Core returns
- periodic usage summaries can continue to queue locally and be retried later

## Code Anchors

- [backend/app/system/services/node_resolution.py](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py)
- [backend/app/system/services/store.py](/home/dan/Projects/Hexe/backend/app/system/services/store.py)
- [backend/app/api/system.py](/home/dan/Projects/Hexe/backend/app/api/system.py)
- [backend/app/system/onboarding/node_budgeting.py](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py)

## See Also

- [API Reference](./api/api-reference.md)
- [Node Budget Management Contract](../nodes/node-budget-management-contract.md)
- [Node Phase 2 Lifecycle Contract](../nodes/node-phase2-lifecycle-contract.md)

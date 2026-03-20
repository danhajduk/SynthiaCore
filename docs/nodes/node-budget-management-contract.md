# Node Budget Management Contract

Status: Partially implemented
Last updated: 2026-03-19

## Purpose

Defines the current Core-side contract for node-declared budget capabilities and operator-configured node budgets.

This foundation covers:

- node declaration of supported budget controls
- Core persistence of node budget setup
- optional customer and provider budget allocations
- operator setup flow in the Core UI
- validation that configured customer/provider slices do not exceed node totals unless overcommit is enabled
- scheduler reservation ledger for scoped work reservations across node, customer, and provider dimensions
- reservation finalization for successful work and release handling for canceled or failed work
- hard-stop scheduler admission checks for node totals and configured customer/provider slices

This document does not yet define:

- runtime usage ingestion
- shared-pool borrowing behavior
- default handling for customers or providers that do not have explicit slice assignments

Those later phases remain queued in the task list.

## Routes

### Node Declaration

- `POST /api/system/nodes/budgets/declaration`
- Auth: `X-Node-Trust-Token`

Used by a trusted node to declare the budget controls it supports and the setup data Core should expose to operators.

### Admin Read

- `GET /api/system/nodes/budgets`
- `GET /api/system/nodes/budgets/{node_id}`
- Auth: admin session/token

Node trust-token reads are also allowed for `GET /api/system/nodes/budgets/{node_id}` while the node remains trusted.

### Admin Setup

- `PUT /api/system/nodes/budgets/{node_id}`
- Auth: admin session/token

Used by operators to configure node totals and optional customer/provider allocations.

## Node Budget Declaration Contract

Declaration request fields:

- `node_id`
- `currency`
- `compute_unit`
- `default_period`
- `supports_money_budget`
- `supports_compute_budget`
- `supports_customer_allocations`
- `supports_provider_allocations`
- `supported_providers[]`
- `setup_requirements[]`
- `suggested_money_limit`
- `suggested_compute_limit`

### Implemented Compute Unit Values

- `cost_units`
- `tokens`
- `requests`
- `gpu_seconds`
- `cpu_seconds`

### Implemented Period Values

- `monthly`
- `daily`
- `manual_reset`

## Node Budget Configuration Contract

Node budget config fields:

- `currency`
- `compute_unit`
- `period`
- `reset_policy`
- `enforcement_mode`
- `overcommit_enabled`
- `shared_customer_pool`
- `shared_provider_pool`
- `node_money_limit`
- `node_compute_limit`

### Implemented Reset Policy Values

- `calendar`
- `rolling`
- `manual`

### Implemented Enforcement Mode Values

- `hard_stop`
- `warn`

## Allocation Contract

Customer allocation items:

- `subject_id`
- `money_limit`
- `compute_limit`

Provider allocation items use the same shape.

Provider allocation validation rules:

- provider allocations are only allowed when the node declared `supports_provider_allocations=true`
- when `supported_providers[]` is declared, configured provider allocation `subject_id` values must be a subset of that declared provider set

## Validation Rules

When `overcommit_enabled=false`:

- sum of customer money allocations must not exceed `node_money_limit`
- sum of provider money allocations must not exceed `node_money_limit`
- sum of customer compute allocations must not exceed `node_compute_limit`
- sum of provider compute allocations must not exceed `node_compute_limit`

Current implementation validates customer and provider slices independently against node totals.

## Setup Status

Core exposes one of these setup states per node:

- `not_declared`
- `needs_configuration`
- `configured`

Meaning:

- `not_declared`: the node has not declared budget capabilities yet
- `needs_configuration`: Core has the node declaration but no operator-configured budget
- `configured`: Core has both declaration and configured budget data

## Operator Setup Flow

The current Core UI setup flow is available on the Addons page node cards.

Operators can:

- inspect the node-declared budget capabilities
- set node-level money and compute totals
- configure customer allocation JSON
- configure provider allocation JSON when supported
- save the resulting budget configuration back to Core

## Example

Example node budget:

- node total money budget: `$10`
- three customers:
  - `cust-a`: `$3.3`
  - `cust-b`: `$3.3`
  - `cust-c`: `$3.3`

This configuration is valid because the total assigned customer money budget is `$9.9`, which is below the node total.

## Scheduler Reservation Contract

Current implementation adds a reservation ledger for queue-based scheduled work submitted through:

- `POST /api/system/scheduler/queue/jobs/submit`
- `POST /api/system/scheduler/queue/jobs/{job_id}/cancel`
- `POST /api/system/scheduler/queue/jobs/{job_id}/complete`

### Reservation Scope Payload

Budget-aware queue submissions use the existing `payload` object with an optional `budget_scope` section:

```json
{
  "budget_scope": {
    "node_id": "node-abc123",
    "customer_id": "cust-a",
    "provider": "openai",
    "money_estimate": 2.5,
    "compute_units": 7
  }
}
```

Implemented fields:

- `node_id`: required for budget reservation creation
- `customer_id`: optional customer slice identifier
- `provider`: optional provider slice identifier
- `money_estimate`: optional estimated money reservation
- `compute_units`: optional estimated compute reservation

If `compute_units` is omitted, Core reserves the queue job's `cost_units` value.

### Reservation Lifecycle

When `payload.budget_scope.node_id` is present and the node already has a configured budget:

- queue submit creates a `reserved` ledger entry
- queue ack may attach the issued `lease_id` to the reservation
- queue completion with `status=DONE` finalizes the reservation and records actual spend
- queue completion with `status=FAILED` releases the reservation
- queue cancel releases the reservation

### Implemented Admission Checks

When the configured node budget uses `enforcement_mode=hard_stop`, queue submit rejects budget-aware work that would exceed:

- `node_money_limit`
- `node_compute_limit`
- configured customer `money_limit` / `compute_limit`
- configured provider `money_limit` / `compute_limit`

Current enforcement uses the reservation ledger:

- `reserved` entries count against admission
- `finalized` entries count using actual spend when reported, otherwise the reserved amount
- `released` entries no longer count against admission

Current rejection errors:

- `node_money_budget_exceeded`
- `node_compute_budget_exceeded`
- `customer_money_budget_exceeded`
- `customer_compute_budget_exceeded`
- `provider_money_budget_exceeded`
- `provider_compute_budget_exceeded`

### Completion Payload Extensions

`POST /api/system/scheduler/queue/jobs/{job_id}/complete` now accepts optional actual-usage fields:

- `actual_money_spend`
- `actual_compute_spend`

If omitted on successful completion, Core finalizes the reservation using the originally reserved amounts.

### Current Limitations

- reservation creation requires a configured node budget when `budget_scope.node_id` is supplied
- current finalized records store reservation versus actual values, but aggregate usage rollups remain a later task
- customer and provider assignment defaults are not yet enforced beyond the declared/configured setup contract
- customer/provider slice enforcement applies only when a matching explicit allocation exists today

## Code Anchors

- `backend/app/system/onboarding/node_budgeting.py`
- `backend/app/api/system.py`
- `frontend/src/core/pages/Addons.tsx`

## See Also

- [Node Onboarding API Contract](./node-onboarding-api-contract.md)
- [API Reference](../core/api/api-reference.md)

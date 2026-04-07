# Feature Request: Service Node Daily Budget Reporting

Status: Not developed
Requested: 2026-04-07

## Request

Add a Core-recognized reporting path where the service node, not only the client node, reports:

- daily budget status
- daily grant-usage summaries

This request applies to node-to-node delegated execution where:

- a client node requests service resolution and authorization from Core
- a provider or service node actually serves the execution
- the grant owner may be the service node rather than the client node

## Current Implemented Behavior

Current implemented behavior is:

- the client or requesting node reports usage with `POST /api/system/nodes/budgets/usage-summary`
- Core stores the usage under the grant owner node derived from `grant_id`
- if reporter and owner differ, Core preserves `reported_by_node_id` in usage metadata

This is implemented in:

- [backend/app/api/system.py](/home/dan/Projects/Hexe/backend/app/api/system.py)
- [backend/app/system/onboarding/node_budgeting.py](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py)

## Problem

Current behavior leaves provider-side budget accounting dependent on the requesting node to submit accurate and timely summaries.

That creates a gap for:

- provider-side reconciliation
- daily operator visibility into actual served grant usage
- comparison between granted work and actually executed work
- detection of missing, delayed, or inconsistent client-side usage reporting

## Abuse-Resistance Gaps This Would Help Close

Current implemented gaps for abusive or faulty client nodes:

- no rate limiting on the node service-resolution, authorization, or usage-summary routes
- no reservation of shared grant capacity at authorization time
- no provider-side confirmation of what was actually served under a grant
- trusted client nodes can under-report, delay-report, or inconsistently report usage
- current usage summaries are accepted from the reporting node without independent service-node reconciliation

This feature request is intended to reduce those gaps by giving Core a provider-side reporting signal for:

- actual daily served grant usage
- actual provider-side budget status
- comparison between client-reported and service-reported totals

## Requested Capability

Add a provider-side reporting contract where the service node reports at least once per day:

- current budget status for the relevant budget-owning node
- per-grant daily usage totals
- optional per-provider and per-model rollups
- optional discrepancy indicators when client-reported and service-reported totals differ

## Minimum Desired Payload Shape

The exact API is not implemented yet, but the minimum useful report should include:

- `node_id`
- `report_date`
- `service`
- `grant_id`
- `used_requests`
- `used_tokens`
- `used_cost_cents`
- `provider`
- `model_id`
- `task_family` when known
- `served_by_node_id`
- `budget_status`

## Desired Semantics

Preferred semantics for the future implementation:

1. client node may continue to report request-side usage for compatibility
2. service node should report served usage daily as provider-side accounting
3. Core should be able to reconcile:
   - client-reported usage
   - service-node-reported usage
   - grant-owner budget totals
4. discrepancies should be visible in admin views or audit output

## Why Daily Reporting

Daily reporting is the minimum cadence that gives:

- provider-side accountability
- budget reconciliation without requiring per-request hot-path coupling
- operator visibility into missing summaries
- a stable rollup window for budget and grant operations

## Relationship To Current Model

This request extends the current model but does not replace the implemented authorization flow.

Current implemented flow remains:

- Core resolves candidate
- Core selects admissible grant
- Core authorizes client node
- client node executes against provider node
- client node reports usage

Requested addition:

- provider node also reports daily grant usage and budget status

## Suggested Acceptance Criteria

- a service node can submit a daily budget/grant status report to Core
- Core persists those reports separately from client usage summaries
- reports are keyed by reporting node and grant id
- Core can display reconciliation between client-side and service-side totals
- missing daily service-node reports are detectable
- delegated execution on provider-owned grants can be audited from provider-side reports
- abusive or inconsistent client-side reporting can be identified through reconciliation gaps

## Related Requests

- [feature-request-probation-grants-and-provider-grant-updates.md](/home/dan/Projects/Hexe/docs/core/feature-request-probation-grants-and-provider-grant-updates.md)
- [node-budget-assignment-flow.md](/home/dan/Projects/Hexe/docs/core/node-budget-assignment-flow.md)

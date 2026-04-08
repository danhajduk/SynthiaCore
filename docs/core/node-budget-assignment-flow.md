# Node Budget Assignment Flow

Status: Implemented
Last Updated: 2026-04-07 16:08 PDT

## Purpose

This document explains, in implementation-verified detail, how Hexe Core decides which budget applies when a trusted node wants another service or node-runtime endpoint to execute a task.

In this document, a budget means the money budget and/or compute-resource budget that Core is allowed to allocate to client nodes and delegated executions.

Current implemented budget limit families include:

- money-style limits such as `max_cost_cents`
- compute-style limits such as `max_tokens`
- compute-style limits such as `max_requests`

This is the concrete flow behind the high-level sequence:

1. a node requests service resolution
2. Core resolves service candidates
3. Core computes which budget owner and grant apply
4. the node requests authorization for one candidate
5. Core returns a short-lived service token plus the selected grant id
6. the node executes and later reports usage against that grant

This behavior is currently implemented by:

- [backend/app/api/system.py](/home/dan/Projects/Hexe/backend/app/api/system.py)
- [backend/app/system/services/node_resolution.py](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py)
- [backend/app/system/onboarding/node_budgeting.py](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py)
- [backend/app/nodes/models_resolution.py](/home/dan/Projects/Hexe/backend/app/nodes/models_resolution.py)
- [backend/tests/test_node_service_resolution_api.py](/home/dan/Projects/Hexe/backend/tests/test_node_service_resolution_api.py)

## Short Answer

Budget assignment is not a separate one-off API that “issues a budget” by itself.

Instead, Core determines which pool of allocatable money and/or compute resources applies to the request, then decides which grant from that pool governs execution.

Instead, Core assigns budget as part of service resolution and service authorization:

- `POST /api/system/nodes/services/resolve` finds executable candidates and attaches a `budget_view` to each candidate
- `POST /api/system/nodes/services/authorize` recomputes that resolution, verifies the requested candidate is still allowed, and returns a short-lived token plus the `grant_id`

The important rule is:

- if the selected service belongs to another provider node, Core evaluates budget on that provider node’s budget configuration
- if no external provider node is identified, Core evaluates budget on the requesting node itself

That selection rule is implemented in [backend/app/system/services/node_resolution.py#L284](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py#L284) through [backend/app/system/services/node_resolution.py#L295](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py#L295).

## Main Actors

### Requesting Node

The node that wants work done.

It sends:

- the task family
- optional task context
- optional preferred provider
- optional preferred model

Later it sends:

- the chosen `service_id`
- optional provider/model selection

### Core

Core is the authority for:

- trust authentication
- governance freshness gating
- governance bundle presence
- candidate resolution
- budget selection
- short-lived service-token issuance

### Provider Node Or Service Endpoint

This is the execution target behind the selected candidate.

Depending on the candidate, the execution target may be:

- a service registered in the service catalog
- a node-derived candidate synthesized from trusted node declarations when no catalog candidate exists

Catalog-first with node-declaration fallback is implemented in [backend/app/system/services/node_resolution.py#L329](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py#L329) through [backend/app/system/services/node_resolution.py#L339](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py#L339).

## The End-To-End Sequence

```text
Requesting Node -> Core: POST /api/system/nodes/services/resolve
Core -> Core: authenticate trusted node
Core -> Core: require governance freshness != outdated
Core -> Core: require governance bundle exists
Core -> Core: find candidate services for task_family
Core -> Core: determine provider node for each candidate
Core -> Core: compute effective budget view for that budget-owning node
Core -> Node: return candidates + budget_view + grant_id

Requesting Node -> Core: POST /api/system/nodes/services/authorize
Core -> Core: repeat trust/governance checks
Core -> Core: recompute resolution from current state
Core -> Core: verify requested candidate is still allowed
Core -> Core: verify budget_view.admissible == true
Core -> Core: issue short-lived service token
Core -> Node: return token + claims + grant_id + selected resolution

Requesting Node -> Execution Target: execute request using returned token

Requesting Node -> Core: POST /api/system/nodes/budgets/usage-summary
Core -> Core: store usage under the grant owner node
```

## Phase 1: Resolution Request

The node starts with `POST /api/system/nodes/services/resolve`.

The route handler is implemented in [backend/app/api/system.py#L1731](/home/dan/Projects/Hexe/backend/app/api/system.py#L1731) through [backend/app/api/system.py#L1788](/home/dan/Projects/Hexe/backend/app/api/system.py#L1788).

### What The Node Sends

The request model is `TaskExecutionResolutionRequest` in [backend/app/nodes/models_resolution.py#L8](/home/dan/Projects/Hexe/backend/app/nodes/models_resolution.py#L8).

The required fields are:

- `node_id`
- `task_family`

Optional fields are:

- `type`
- `task_context`
- `preferred_provider`
- `preferred_model`

### Input Normalization Rules

The request model applies two important normalization rules:

1. top-level `type` is merged into `task_context.type`
2. if both are present and disagree, validation fails with `task_type_conflict`

This is implemented in [backend/app/nodes/models_resolution.py#L33](/home/dan/Projects/Hexe/backend/app/nodes/models_resolution.py#L33) through [backend/app/nodes/models_resolution.py#L44](/home/dan/Projects/Hexe/backend/app/nodes/models_resolution.py#L44).

### Canonical Task Family Rules

The same model rejects task-family ids that encode provider or context information into the canonical task-family string.

Examples rejected by validation:

- `task.summarization.openai`
- `task.summarization.email` when `content_type=email`
- `task.summarization.email` when `type=email`

This is implemented in [backend/app/nodes/models_resolution.py#L46](/home/dan/Projects/Hexe/backend/app/nodes/models_resolution.py#L46) through [backend/app/nodes/models_resolution.py#L58](/home/dan/Projects/Hexe/backend/app/nodes/models_resolution.py#L58), with coverage in [backend/tests/test_node_service_resolution_api.py](/home/dan/Projects/Hexe/backend/tests/test_node_service_resolution_api.py).

## Phase 2: Core Admission Checks Before Budget Assignment

Before Core even tries to assign a budget, the resolve route checks:

- `node_id` must be present
- `X-Node-Trust-Token` must be present
- node resolution service must be available
- node registrations store must be available
- trust issuance must be available
- node budgeting must be available
- the node trust token must authenticate successfully
- the registry record must exist and be `trusted`
- governance freshness must not be `outdated`
- a governance bundle must already exist

These checks are implemented in [backend/app/api/system.py#L1737](/home/dan/Projects/Hexe/backend/app/api/system.py#L1737) through [backend/app/api/system.py#L1759](/home/dan/Projects/Hexe/backend/app/api/system.py#L1759).

### Governance Freshness Block

If governance freshness is `outdated`, Core rejects new resolution and authorization requests with HTTP `409` and `error=node_governance_outdated`.

That block is enforced by `_reject_if_outdated_for_new_contracts(...)` in [backend/app/api/system.py#L644](/home/dan/Projects/Hexe/backend/app/api/system.py#L644) through [backend/app/api/system.py#L655](/home/dan/Projects/Hexe/backend/app/api/system.py#L655).

## Phase 3: Candidate Discovery

After admission succeeds, Core calls `NodeServiceResolutionService.resolve_for_node(...)`.

That method is implemented in [backend/app/system/services/node_resolution.py](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py).

### Candidate Sources

Core builds candidates from two sources:

1. service catalog entries from the service catalog store
2. if no catalog candidates survive filtering, synthesized candidates from trusted node declarations

This fallback behavior is implemented in [backend/app/system/services/node_resolution.py#L329](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py#L329) through [backend/app/system/services/node_resolution.py#L339](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py#L339).

### Candidate Filtering

For each candidate source, Core keeps the candidate only if all of the following are true:

- the requested `task_family` appears in the candidate `capabilities`
- service health is `ok`, `healthy`, or `unknown`
- if `preferred_provider` is given, the candidate provider matches it
- if `preferred_model` is given, the candidate’s model list is narrowed to that model and must remain non-empty
- the computed budget view is not in `no_matching_grant`, `not_configured`, `revoked`, or `expired`

This filtering logic is implemented in [backend/app/system/services/node_resolution.py#L261](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py#L261) through [backend/app/system/services/node_resolution.py#L298](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py#L298).

### Governance Constraint Verified Here

The explicit governance constraint enforced directly inside `resolve_for_node(...)` is `allowed_task_families`.

If the governance bundle includes `routing_policy_constraints.allowed_task_families` and the requested task family is not in that set, Core returns no candidates.

That check happens earlier in the same method before candidate iteration.

## Phase 4: Determining Which Node Owns The Budget

This is the most important part of “budget assignment.”

Core does not always evaluate budget on the requesting node.

It first tries to determine whether the selected candidate belongs to a provider node. If so, the provider node becomes the budget owner for that candidate.

### How Core Infers The Provider Node

`_resolve_provider_node_id(...)` tries, in order, to infer the provider node from candidate metadata such as:

- explicit `node_id`
- `addon_registry.node_id`
- `declared_capacity.node_id`
- `service_capacity.node_id`
- model-routing registry matches
- registered node API base URLs matched against candidate endpoint/base URL

This logic is implemented in [backend/app/system/services/node_resolution.py](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py) near `_resolve_provider_node_id(...)`.

### The Budget Owner Rule

When Core computes the budget view, it calls:

```python
budget_service.effective_budget_view(
    node_id=provider_node_id or request.node_id,
    task_family=task_family,
    provider=provider or None,
    model_id=preferred_model or None,
)
```

This means:

- if `provider_node_id` is known, use that node’s budget
- otherwise use the requesting node’s budget

Here, “use that node’s budget” means:

- use that node’s allocatable money limits
- use that node’s allocatable compute limits
- select the grant that represents the allowed slice of those resources for the request

That exact rule is implemented in [backend/app/system/services/node_resolution.py#L290](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py#L290) through [backend/app/system/services/node_resolution.py#L295](/home/dan/Projects/Hexe/backend/app/system/services/node_resolution.py#L295).

### What This Means Operationally

There are two common cases.

Case 1: self-executing or locally-owned execution

- the requester resolves to its own execution endpoint or no separate provider node is identified
- the requester’s own node budget is evaluated

Case 2: delegated execution to another provider node

- the candidate resolves to another node that provides the requested provider/model
- the provider node’s budget is evaluated
- the grant id returned to the requesting node belongs to the provider node’s budget space

This delegated-budget behavior is covered by [backend/tests/test_node_service_resolution_api.py](/home/dan/Projects/Hexe/backend/tests/test_node_service_resolution_api.py), specifically the test that confirms the delegating node receives a candidate whose `budget_view.budget_node_id` is the provider node.

## Phase 5: Grant Selection Inside The Budget Service

The actual grant selection happens in `NodeBudgetService.effective_budget_view(...)`.

That method is implemented in [backend/app/system/onboarding/node_budgeting.py#L856](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L856) through [backend/app/system/onboarding/node_budgeting.py#L954](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L954).

### Step 1: Require Budget Configuration

Core first loads the target node’s budget config.

If there is no config, it returns:

- `status=not_configured`
- `admissible=false`
- `reason=node_budget_not_configured`

That happens in [backend/app/system/onboarding/node_budgeting.py#L865](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L865) through [backend/app/system/onboarding/node_budgeting.py#L879](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L879).

### Step 2: Derive Grants

Core then derives the current grants for that node.

Those grants come from:

- the node-level budget grant
- any customer allocation grants
- any provider allocation grants

For service resolution, the relevant ones are usually:

- a provider-scoped grant for the selected provider
- otherwise the node-scoped grant

### Step 3: Prefer Provider-Scoped Grants

If a `provider` is present in the request:

- Core first looks for a `scope_kind=provider` grant whose `subject_id` matches that provider

That lookup is implemented in [backend/app/system/onboarding/node_budgeting.py#L883](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L883) through [backend/app/system/onboarding/node_budgeting.py#L893](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L893).

### Step 4: Enforce Hard Provider Slices When Configured

If provider allocations exist for that node, and `shared_provider_pool` is `false`, then Core will not fall back to the node-wide grant for an unmatched provider.

Instead it returns:

- `status=no_matching_grant`
- `admissible=false`
- `reason=provider_budget_allocation_required`

That rule is implemented in [backend/app/system/onboarding/node_budgeting.py#L894](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L894) through [backend/app/system/onboarding/node_budgeting.py#L904](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L904).

### Step 5: Fall Back To The Node-Scoped Grant

If no provider-scoped grant is selected, Core falls back to the node-scoped grant.

That happens in [backend/app/system/onboarding/node_budgeting.py#L905](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L905) through [backend/app/system/onboarding/node_budgeting.py#L917](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L917).

### Step 6: Compute Consumption And Remaining Budget

After selecting a grant, Core loads usage reports for that exact `grant_id` and computes:

- consumed requests
- consumed tokens
- consumed cost cents
- remaining limits for each configured limit family

So the effective grant calculation is fundamentally:

- start from the allocatable money and/or compute resources represented by the selected grant
- subtract previously reported usage
- decide whether enough allocatable resource remains to admit more work

This happens in [backend/app/system/onboarding/node_budgeting.py#L919](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L919) through [backend/app/system/onboarding/node_budgeting.py#L930](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L930).

### Step 7: Decide Admissibility

The selected grant is admissible only when:

- grant `status` is `active`
- every computed remaining limit is still greater than zero

This rule is implemented in [backend/app/system/onboarding/node_budgeting.py#L931](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L931) through [backend/app/system/onboarding/node_budgeting.py#L953](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L953).

If the grant exists but remaining budget is exhausted, Core returns:

- `status=exhausted`
- `admissible=false`
- `reason=budget_exhausted`

## Phase 6: What The Resolve Response Really Means

The resolve response does not authorize execution yet.

It returns candidate information plus enough budget state for the node to understand what Core would authorize if the node immediately asked for authorization.

Each candidate may include:

- `service_id`
- `provider_node_id`
- `provider_api_base_url`
- `provider`
- `models_allowed`
- `required_scopes`
- `grant_id`
- `budget_view`

The candidate and budget view shapes are defined in [backend/app/nodes/models_resolution.py#L61](/home/dan/Projects/Hexe/backend/app/nodes/models_resolution.py#L61) through [backend/app/nodes/models_resolution.py#L101](/home/dan/Projects/Hexe/backend/app/nodes/models_resolution.py#L101).

Important detail:

- the `grant_id` shown in a resolve candidate is copied from `budget_view.grant_id`
- that means the resolve response is already telling the node which grant Core currently expects to govern execution for that candidate

## Phase 7: Authorization Request

After choosing a candidate, the node calls `POST /api/system/nodes/services/authorize`.

The route handler is implemented in [backend/app/api/system.py#L1790](/home/dan/Projects/Hexe/backend/app/api/system.py#L1790) through [backend/app/api/system.py#L1874](/home/dan/Projects/Hexe/backend/app/api/system.py#L1874).

### Important Design Rule

Authorization does not trust the previous resolve result blindly.

Instead, it recomputes resolution from current state by calling `resolve_for_node(...)` again.

That means budget assignment is checked again at authorization time, not only at discovery time.

This recomputation happens in [backend/app/api/system.py#L1819](/home/dan/Projects/Hexe/backend/app/api/system.py#L1819) through [backend/app/api/system.py#L1823](/home/dan/Projects/Hexe/backend/app/api/system.py#L1823).

### Candidate Match Rules During Authorization

Core then tries to find a resolved candidate that matches the authorization request’s:

- `service_id` if supplied
- `provider` if supplied
- `model_id` if supplied

If no candidate matches, Core rejects the request with:

- HTTP `403`
- `error=service_candidate_not_authorized`

This logic is implemented in [backend/app/api/system.py#L1826](/home/dan/Projects/Hexe/backend/app/api/system.py#L1826) through [backend/app/api/system.py#L1840](/home/dan/Projects/Hexe/backend/app/api/system.py#L1840).

### Final Budget Gate

Even if the candidate matches, authorization still fails unless:

- `candidate.budget_view` exists
- `candidate.budget_view.admissible` is `true`

Otherwise Core returns:

- HTTP `403`
- `error=budget_not_admissible`

That final gate is implemented in [backend/app/api/system.py#L1841](/home/dan/Projects/Hexe/backend/app/api/system.py#L1841) through [backend/app/api/system.py#L1842](/home/dan/Projects/Hexe/backend/app/api/system.py#L1842).

## Phase 8: What Core Returns On Grant

If authorization succeeds, Core issues a short-lived service token and returns:

- `service_id`
- `provider`
- `model_id`
- `grant_id`
- `required_scopes`
- `expires_at`
- `token`
- `claims`
- `resolution`

The token issuer uses:

- `sub = node_id`
- `aud = candidate.service_id`
- `scp = candidate.required_scopes`

That token issuance happens through `_issue_service_token_for_node(...)` in [backend/app/api/system.py#L566](/home/dan/Projects/Hexe/backend/app/api/system.py#L566) through [backend/app/api/system.py#L584](/home/dan/Projects/Hexe/backend/app/api/system.py#L584), and is used by the authorize route at [backend/app/api/system.py#L1843](/home/dan/Projects/Hexe/backend/app/api/system.py#L1843) through [backend/app/api/system.py#L1847](/home/dan/Projects/Hexe/backend/app/api/system.py#L1847).

### Why The Response Contains Both Token And Grant

The response gives the node two separate things:

- authorization to call the selected service now
- the budget identity that must be used for later accounting

Those are related, but they are not the same object:

- the token is an execution credential
- the `grant_id` is the budget/accounting key

## Phase 9: Usage Reporting Closes The Loop

After execution, the node reports usage with `POST /api/system/nodes/budgets/usage-summary`.

Current implemented reporter responsibility:

- the requesting or client node is the component expected to submit the usage summary to Core
- the service or provider node is not the primary usage reporter in the current implemented contract
- when the grant belongs to another node, Core still stores the usage under the grant owner node while preserving the reporting node id in metadata

The key budget-assignment rule here is that Core stores usage under the grant owner node, not necessarily under the reporting node.

### How The Owner Node Is Recovered

`grant_owner_node_id(...)` parses grant ids shaped like `grant:<node_id>:...`.

That helper is implemented in [backend/app/system/onboarding/node_budgeting.py#L956](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L956) through [backend/app/system/onboarding/node_budgeting.py#L964](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L964).

### How Usage Is Stored

When usage is reported:

- Core extracts the grant owner node id from `grant_id`
- if the reporting node is different, usage is still stored under the owner node
- Core adds `reported_by_node_id` to metadata when reporter and owner differ

This is implemented in [backend/app/system/onboarding/node_budgeting.py#L966](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L966) through [backend/app/system/onboarding/node_budgeting.py#L1008](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L1008).

This behavior is covered by the delegated-resolution test in [backend/tests/test_node_service_resolution_api.py](/home/dan/Projects/Hexe/backend/tests/test_node_service_resolution_api.py), where a delegating node reports usage and Core stores it under the provider node while preserving `reported_by_node_id`.

## Requested Follow-Up

Status: Not developed

Requested feature:

- service node should report daily budget status to Core
- service node should report daily grant-usage summaries to Core for grants it serves

Reason for request:

- current implemented contract makes the requesting or client node the usage reporter
- this leaves service-node-side execution and provider-side accounting dependent on client-originated summaries
- a service-node-originated daily report would provide an operator-facing reconciliation path and a provider-side source of truth for actual served grant usage

See the tracked request in [feature-request-service-node-daily-budget-reporting.md](/home/dan/Projects/Hexe/docs/core/feature-request-service-node-daily-budget-reporting.md).

## Grant Lifecycle

The current grant lifecycle is mostly derived from budget configuration and time windows, not managed as a separate long-lived state machine stored in its own table.

In practice, a grant moves through these stages:

1. budget capability is declared for a node
2. budget config and optional allocations are stored for that node
3. Core derives grants from that config
4. derived grants are published in budget policy and governance material
5. one derived grant is selected during resolve/authorize
6. usage accumulates against that grant id
7. the grant eventually becomes non-admissible or expires

### Lifecycle Diagram

```text
Budget capability declared
        |
        v
Node budget configured
and allocations stored
        |
        v
Core derives grants
from current config
        |
        v
Grant appears in
budget_policy.grants
and governance bundle
        |
        v
Grant selected during
resolve/authorize
        |
        v
Usage summaries reported
against grant_id
        |
        +------------------------------+
        |                              |
        v                              v
Grant still admissible           Grant no longer admissible
status=active                    exhausted / unmatched / removed
remaining budget > 0             or period ended
        |                              |
        |                              v
        +-----------------------> Expired or effectively unusable
```

### Stage 1: Derived From Budget Setup

Grants are produced by `derive_grants(...)` from:

- the node-wide budget config
- customer allocations
- provider allocations

This is implemented in [backend/app/system/onboarding/node_budgeting.py#L796](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L796) through [backend/app/system/onboarding/node_budgeting.py#L851](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L851).

Important detail:

- the current node budgeting flow derives grants on demand
- it does not persist a separate mutable “live grant record” that is updated through many workflow states

### Stage 2: Published As Policy Material

Derived grants are included in the node budget policy returned by `budget_policy(...)`.

That happens in [backend/app/system/onboarding/node_budgeting.py#L748](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L748) through [backend/app/system/onboarding/node_budgeting.py#L794](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L794).

So a grant becomes visible to a node when:

- Core issues or refreshes governance
- or the node fetches/refreshes the budget policy directly

### Stage 3: Selected For Execution

During service resolution and authorization, Core selects one derived grant and returns its `grant_id` in the candidate/authorization payload if that grant is currently admissible.

That selection happens in [backend/app/system/onboarding/node_budgeting.py#L856](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L856) through [backend/app/system/onboarding/node_budgeting.py#L954](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L954).

### Stage 4: Accumulates Usage

After execution, usage is reported against the selected `grant_id`.

Core stores usage summaries keyed by:

- owner node id
- service
- grant id
- period window

This happens in [backend/app/system/onboarding/node_budgeting.py#L966](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L966) through [backend/app/system/onboarding/node_budgeting.py#L1008](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L1008).

### Stage 5: May Become Non-Admissible Before Expiry

A grant can stop being usable even before it reaches its time boundary.

That happens when:

- no remaining configured limit is above zero
- provider slicing rules mean no matching provider grant is available
- the backing node budget config is gone

In those cases, Core can still derive the structural grant shape or determine the grant path, but `effective_budget_view(...)` will mark the result non-admissible.

Common reasons returned by the effective budget view are:

- `node_budget_not_configured`
- `provider_budget_allocation_required`
- `grant_not_found`
- `budget_exhausted`

### Stage 6: Expires At Period End

Grant status is derived from the configured budget period window.

When the grant record is built, Core marks it:

- `active` if `period_end` is still in the future
- `expired` if `period_end` is in the past or at the current time

That status assignment happens in `_grant_record(...)` in [backend/app/system/onboarding/node_budgeting.py#L1505](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L1505), specifically [backend/app/system/onboarding/node_budgeting.py#L1528](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L1528).

### Revocation Versus Expiry

There is an important distinction between expiry and revocation in the current implementation.

Expiry:

- is a derived grant status based on `period_end`

Revocation:

- is currently communicated through revocation payloads and retained topics when budget policy is removed or changed
- is not the main steady-state lifecycle stored in the derived grant list returned by `derive_grants(...)`

Revocation payload generation is implemented in [backend/app/system/onboarding/node_budgeting.py#L1433](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L1433) through [backend/app/system/onboarding/node_budgeting.py#L1458](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L1458).

## Worked Example

Here is the implementation-backed mental model for the common delegated case.

1. Node `A` wants `task.summarization`.
2. Core resolves candidate `summary-service`.
3. Core infers that `summary-service` belongs to provider node `B`.
4. Core computes the effective budget view using node `B` as the budget node.
5. Core selects either:
   - provider grant for `openai`, if one exists
   - otherwise node-wide grant for `B`
6. Core returns the candidate with:
   - `provider_node_id = B`
   - `budget_view.budget_node_id = B`
   - `grant_id = grant:B:...`
7. Node `A` asks to authorize `summary-service`.
8. Core recomputes resolution, confirms the candidate still matches, and confirms `budget_view.admissible=true`.
9. Core returns:
   - service token for audience `summary-service`
   - `grant_id = grant:B:...`
10. Node `A` executes the request.
11. Node `A` reports usage with that `grant_id`.
12. Core stores the usage under node `B`’s budget record and marks `reported_by_node_id = A`.

## Failure Cases That Matter

The most important budget-assignment failure modes are:

- `node_trust_token_required`: node did not send trust token
- `untrusted_node`: token or registration does not represent a trusted node
- `node_governance_outdated`: governance freshness is too old for new contracts
- `governance_not_issued`: node has no governance bundle yet
- `service_provider_not_found`: recomputed resolution found no candidate
- `service_candidate_not_authorized`: requested candidate did not match the currently resolved candidates
- `budget_not_admissible`: candidate exists but no admissible grant is currently available

Budget-specific non-admissible causes visible in `budget_view` include:

- `node_budget_not_configured`
- `provider_budget_allocation_required`
- `grant_not_found`
- `budget_exhausted`

## Current Safeguards And Gaps

This is the current implementation-backed answer to whether the system protects itself from abusive or incorrect client nodes.

### Current Safeguards

- only trusted nodes can call `resolve`, `authorize`, and `usage-summary`
- governance freshness blocks stale nodes from receiving new contracts
- authorization is scoped to the selected service audience and required execution scopes
- grants must be currently admissible before Core returns authorization
- provider hard-slice rules can prevent fallback to a wider shared node budget when `shared_provider_pool=false`
- service tokens are short-lived

These controls are implemented in:

- [backend/app/api/system.py#L1687](/home/dan/Projects/Hexe/backend/app/api/system.py#L1687) through [backend/app/api/system.py#L1874](/home/dan/Projects/Hexe/backend/app/api/system.py#L1874)
- [backend/app/api/system.py#L566](/home/dan/Projects/Hexe/backend/app/api/system.py#L566) through [backend/app/api/system.py#L586](/home/dan/Projects/Hexe/backend/app/api/system.py#L586)
- [backend/app/system/auth/tokens.py#L149](/home/dan/Projects/Hexe/backend/app/system/auth/tokens.py#L149) through [backend/app/system/auth/tokens.py#L181](/home/dan/Projects/Hexe/backend/app/system/auth/tokens.py#L181)
- [backend/app/system/onboarding/node_budgeting.py#L856](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L856) through [backend/app/system/onboarding/node_budgeting.py#L954](/home/dan/Projects/Hexe/backend/app/system/onboarding/node_budgeting.py#L954)

### Current Gaps For Abusive Clients

Current implementation gaps that matter for abusive or faulty client nodes:

- no rate limiting is implemented for `POST /api/system/nodes/services/resolve`
- no rate limiting is implemented for `POST /api/system/nodes/services/authorize`
- no rate limiting is implemented for `POST /api/system/nodes/budgets/usage-summary`
- authorization does not reserve grant capacity, so multiple clients can be authorized against the same shared grant before usage catches up
- Core currently accepts trusted client usage summaries without provider-side confirmation of what was actually served
- the current grant model does not bind a grant id to a single task family
- current usage reporting does not validate that a reported grant id corresponds to a specific previously authorized execution instance

Operationally, this means the current system has trust, scope, and admissibility controls, but not strong anti-abuse accounting protections against a malicious trusted client.

## Open Design Gaps

Beyond abusive-client reporting concerns, the current budgeting and grant system still has several design gaps that matter for correctness, fairness, and auditability.

### 1. Authorization Is Not A Reservation

Core checks whether a grant is admissible at authorization time, but it does not reserve capacity for that caller afterward.

That means:

- multiple nodes can be authorized against the same shared grant
- all of them can act on the same visible remaining budget window
- oversubscription is possible before later usage summaries reduce the available balance

### 2. Shared Grant Pools Have No Fairness Control

When multiple client nodes consume the same provider-owned grant pool, there is currently no built-in fairness mechanism such as:

- per-client subgrants
- weighted allocation
- concurrency caps per consumer
- request scheduling by consumer share

In practice, the fastest or noisiest consumer may dominate the shared pool.

### 3. Usage Reporting Is Not Bound To A Specific Authorized Execution

Current usage-summary ingestion accepts a trusted reporter and a `grant_id`, but it does not require proof that the report corresponds to one exact previously authorized execution instance.

That means Core does not currently enforce a durable one-to-one chain like:

- authorization event
- execution instance
- usage settlement record

### 4. Grant Scope Does Not Include Task Family Or Consumer Identity

The current grant model is mainly scoped by:

- budget owner node
- scope kind
- optional provider subject
- period window

It is not currently scoped by:

- task family
- consuming client node
- single authorization contract

That keeps the system simple, but it weakens isolation and replay resistance across different execution contexts.

### 5. No Pending-Consumption State Between Authorization And Usage

There is currently no explicit “pending spend” or “in-flight consumption” bucket between:

- the moment Core authorizes execution
- the moment usage is later reported

That leaves a reconciliation gap for:

- long-running executions
- failed executions that still consumed provider resources
- delayed or missing usage reports

### 6. Limited Historical Audit Reconstruction

Grants are derived from current policy state rather than stored as long-lived mutable contracts with their own lifecycle records.

That means historical analysis can be harder when:

- budget configuration changes
- allocations change
- period windows roll over
- operators want to reconstruct exactly what policy snapshot governed a past execution

### 7. No Built-In Duplicate Or Idempotency Guard For Usage Summaries

The current usage-summary flow does not expose a dedicated idempotency key or settlement identifier for each usage report submission.

That makes duplicate, repeated, or retried submissions harder to distinguish from legitimate updates at the contract level.

### 8. No Provider-Side Confirmation In The Current Contract

The current contract treats the client node as the primary usage reporter.

Without a provider-side reporting or settlement path, Core cannot independently confirm:

- what was actually served
- what model/provider actually executed
- whether client-reported totals match provider-observed work

This is the main reason the follow-up request for service-node daily reporting exists.

## What Budget Assignment Is Not

To avoid confusion, the current implementation does not do the following during resolve/authorize:

- reserve budget units ahead of execution in a separate reservation record
- decrement grant counters directly during authorization
- mint a standalone “budget token”

Instead:

- authorization checks that a grant is currently admissible
- execution happens outside Core’s hot path
- accounting is reconciled later through usage summaries keyed by `grant_id`

Queue-based reservation logic does exist elsewhere in the budgeting subsystem, but that is a separate scheduler compatibility path and not the node service resolution/authorization flow documented here.

## See Also

- [node-service-resolution-and-budgeting.md](/home/dan/Projects/Hexe/docs/core/node-service-resolution-and-budgeting.md)
- [node-budget-management-contract.md](/home/dan/Projects/Hexe/docs/nodes/node-budget-management-contract.md)
- [feature-request-service-node-daily-budget-reporting.md](/home/dan/Projects/Hexe/docs/core/feature-request-service-node-daily-budget-reporting.md)
- [feature-request-probation-grants-and-provider-grant-updates.md](/home/dan/Projects/Hexe/docs/core/feature-request-probation-grants-and-provider-grant-updates.md)

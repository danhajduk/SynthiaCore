# Node Lifecycle

Status: Partially implemented
Last updated: 2026-03-20 10:16

This document defines the canonical node lifecycle model for node-related documentation and maps it to the currently verified Core behavior.

Public-facing naming note: Hexe Nodes is the display label used for this subsystem, and active MQTT topic literals now use the `hexe` namespace. Some stable technical identifiers still retain legacy forms where compatibility matters.

Primary code:
- `backend/app/system/onboarding/sessions.py`
- `backend/app/system/onboarding/registrations.py`
- `backend/app/system/onboarding/governance.py`

## Canonical Node Lifecycle

Canonical node lifecycle states:

- `unconfigured`
- `bootstrap_connecting`
- `bootstrap_connected`
- `core_discovered`
- `registration_pending`
- `pending_approval`
- `trusted`
- `capability_setup_pending`
- `capability_declaration_in_progress`
- `capability_declaration_accepted`
- `capability_declaration_failed_retry_pending`
- `operational`
- `degraded`

Current documentation rule:

- this lifecycle enum is the canonical end-to-end node model across node-related docs
- Core does not currently project every state as a first-class API lifecycle label
- some states are node-local runtime/setup states rather than current Core-owned fields

Current implementation alignment:

- Implemented and clearly represented in current Core docs/contracts:
  - `pending_approval`
  - `trusted`
  - `capability_setup_pending`
  - `operational`
  - `degraded`
- Documented but not implemented as a single Core lifecycle enum:
  - `unconfigured`
  - `bootstrap_connecting`
  - `bootstrap_connected`
  - `core_discovered`
  - `registration_pending`
  - `capability_declaration_in_progress`
  - `capability_declaration_accepted`
  - `capability_declaration_failed_retry_pending`

## State Meanings

- `unconfigured`: node has local identity/runtime prerequisites missing and cannot begin bootstrap yet
- `bootstrap_connecting`: node is attempting to reach Core's bootstrap MQTT listener
- `bootstrap_connected`: node has transport connectivity to the bootstrap listener
- `core_discovered`: node has consumed retained bootstrap metadata from `hexe/bootstrap/core`
- `registration_pending`: node has started onboarding registration/session flow but has not yet reached approved trust activation
- `pending_approval`: Core has a pending onboarding session awaiting operator decision
- `trusted`: trust activation completed and the node has trusted-node credentials
- `capability_setup_pending`: trusted node still needs provider/task/setup work before declaration and governance complete
- `capability_declaration_in_progress`: node is actively preparing or submitting capability declaration
- `capability_declaration_accepted`: capability declaration completed successfully and Core accepted the resulting capability profile
- `capability_declaration_failed_retry_pending`: capability declaration failed and the node is waiting to retry
- `operational`: node is ready for normal operation
- `degraded`: node was previously operational or trusted but is now impaired and should surface operator-visible warning/degraded behavior

## Sequence

Canonical sequence:

1. `unconfigured`
2. `bootstrap_connecting`
3. `bootstrap_connected`
4. `core_discovered`
5. `registration_pending`
6. `pending_approval`
7. `trusted`
8. `capability_setup_pending`
9. `capability_declaration_in_progress`
10. `capability_declaration_accepted`
11. `operational`

Common side paths:

- capability declaration failure:
  - `capability_declaration_in_progress -> capability_declaration_failed_retry_pending -> capability_declaration_in_progress`
- degraded runtime:
  - `operational -> degraded`
- trusted restart / fast path:
  - `trusted -> capability_setup_pending -> operational`

## Projection Boundary

Lifecycle state is not the same thing as readiness or synchronization projection.

Current separate projections in Core docs:

- `capability_status`
- `governance_sync_status`
- `operational_ready`
- `governance_freshness_state`

The canonical lifecycle enum above should therefore be read as the node-facing state-machine model, while current Core APIs may expose only parts of it directly.

## Onboarding Session Lifecycle

Status: Implemented

Node onboarding sessions move through these verified states:

- `pending`
- `approved`
- `rejected`
- `expired`
- `consumed`
- `cancelled`

Current allowed transitions in code:

- `pending` -> `approved`
- `pending` -> `rejected`
- `pending` -> `expired`
- `pending` -> `cancelled`
- `approved` -> `consumed`

Each session records state-history entries with timestamps, previous state, next state, actor identity, and reason.

## Registration Lifecycle

Status: Implemented

- Approved onboarding sessions can be converted into node registration records.
- Registrations are stored with node identity, trust status, capability summary, approval metadata, and lifecycle timestamps.
- Trust status values accepted by the registration store are `pending`, `approved`, `trusted`, `revoked`, and `rejected`.

## Governance Lifecycle

Status: Implemented

- Governance bundles are issued per node and capability profile.
- Each bundle records `node_id`, `capability_profile_id`, `governance_version`, and `issued_timestamp`.
- Baseline issuance increments versions using the `gov-vN` pattern when a new revision is created.

## Operational Lifecycle Guidance

Status: Partially implemented

- `capability_setup_pending` is the blocked post-trust pre-operational state in current Core docs
- trusted startup may pass through `capability_setup_pending` and continue immediately when accepted capability state and fresh governance are already present
- `capability_declaration_accepted` corresponds to current Core projection `capability_status=accepted`
- transition to `operational` requires accepted capabilities, issued governance, and `operational_ready=true`
- `operational_ready` is the canonical readiness signal if lifecycle labeling and readiness projection differ during compatibility windows
- setup and runtime polling use `GET /api/system/nodes/operational-status/{node_id}`

## See Also

- [node-onboarding-registration-architecture.md](./node-onboarding-registration-architecture.md)
- [node-onboarding-api-contract.md](./node-onboarding-api-contract.md)
- [node-phase2-lifecycle-contract.md](./node-phase2-lifecycle-contract.md)
- [../temp-ai-node/README.md](../temp-ai-node/README.md)

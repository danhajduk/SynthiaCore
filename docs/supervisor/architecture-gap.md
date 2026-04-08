# Supervisor Architecture Gap

Status: Implemented

This document compares the current Hexe Supervisor implementation with the target `Core -> Supervisor -> Nodes` architecture described in the draft design.

## Source Of Truth

- Current implementation:
  - `backend/app/supervisor/service.py`
  - `backend/app/supervisor/router.py`
  - `backend/app/system/runtime/service.py`
  - `backend/app/system/onboarding/registrations.py`
  - `backend/app/nodes/registry.py`
  - `backend/app/system/mqtt/runtime_boundary.py`
  - `systemd/user/synthia-supervisor.service.in`
- Target architecture draft:
  - `docs/Upgrades/synthia-core-supervisor-node-design.md`
- Canonical architecture alignment:
  - `/home/dan/Projects/Synthia/docs/supervisor/README.md`
  - `/home/dan/Projects/Synthia/docs/supervisor/runtime-and-supervision.md`

## Target Architecture Summary

Status: Documented but not implemented

The draft architecture defines this runtime hierarchy:

- Core -> governance and orchestration
- Supervisor -> host-local runtime authority
- Nodes -> execution units and external functionality

Under that model:

- Core owns trust, policy, capability registry, system configuration, operator APIs, and platform orchestration.
- Supervisor owns host resources, local runtime registration, lifecycle control, host telemetry, process/container management, restart policies, and local resource policy enforcement.
- Nodes register with the local Supervisor, then onboard with Core.

Source:

- `docs/Upgrades/synthia-core-supervisor-node-design.md`

## Current Supervisor Boundary

Status: Implemented

The current Supervisor implementation already owns:

- host resource summaries
- host process summaries
- workload admission context
- standalone addon runtime inspection
- standalone addon start/stop/restart actions
- compose-based realization for host-local standalone addon workloads
- host-local `cloudflared` runtime realization

This is implemented through:

- `GET /api/supervisor/health`
- `GET /api/supervisor/info`
- `GET /api/supervisor/resources`
- `GET /api/supervisor/runtime`
- `GET /api/supervisor/admission`
- `GET /api/supervisor/nodes`
- `POST /api/supervisor/nodes/{node_id}/start`
- `POST /api/supervisor/nodes/{node_id}/stop`
- `POST /api/supervisor/nodes/{node_id}/restart`

Code anchors:

- `backend/app/supervisor/service.py`
- `backend/app/supervisor/router.py`
- `backend/app/system/runtime/service.py`

## Current Node Boundary

Status: Implemented

Current Node registry and trust-oriented status are still Core-owned.

Implemented ownership includes:

- Node registration persistence in `data/node_registrations.json`
- Node registry projection and governance/trust status assembly
- Core-side node listing and lookup APIs

Code anchors:

- `backend/app/system/onboarding/registrations.py`
- `backend/app/nodes/registry.py`
- `backend/app/nodes/service.py`

## Key Gaps

### Gap 1: Supervisor-managed nodes are not real Nodes yet

Status: Implemented but undocumented

Current `SupervisorDomainService._managed_nodes()` maps standalone addon runtimes into `ManagedNodeSummary`.

That means current Supervisor "nodes" are:

- standalone addon runtimes discovered from the services directory

They are not:

- externally onboarded Nodes registered through a Node-to-Supervisor contract

Code anchor:

- `backend/app/supervisor/service.py`

### Gap 2: Real Node runtime truth is only partially Supervisor-owned

Status: Partially implemented

The target architecture expects runtime truth to flow:

- Node -> Supervisor -> Core

In the current repository state:

- Core still owns persistent Node registration records, trust, onboarding approval, governance, and registry projection
- Supervisor now owns a separate runtime registration, heartbeat, freshness, and action-intent store for real Nodes
- Core can consume that Supervisor-owned runtime slice in read-only form on node registry views

This means the runtime contract now exists, but lifecycle realization for real Nodes is still at the contract/state layer rather than a full process or container executor layer.

Code anchors:

- `backend/app/system/onboarding/registrations.py`
- `backend/app/nodes/registry.py`
- `backend/app/system/runtime/service.py`

### Gap 3: Real Node registration / heartbeat API was previously missing

Status: Implemented

The draft architecture describes Supervisor APIs for:

- runtime registration
- heartbeat publication
- runtime lifecycle control for registered local runtimes

The current Supervisor router now exposes:

- `POST /api/supervisor/runtimes/register`
- `POST /api/supervisor/runtimes/heartbeat`
- `GET /api/supervisor/runtimes`
- `GET /api/supervisor/runtimes/{node_id}`
- `POST /api/supervisor/runtimes/{node_id}/start`
- `POST /api/supervisor/runtimes/{node_id}/stop`
- `POST /api/supervisor/runtimes/{node_id}/restart`

Code anchor:

- `backend/app/supervisor/router.py`

### Gap 4: Docker/runtime ownership is still split between Core and Supervisor

Status: Partially implemented

Supervisor currently owns Docker or process realization for:

- standalone addon compose workloads
- `cloudflared` edge runtime

Core still directly owns runtime execution for:

- embedded MQTT runtime boundary

This split is functional today, but it does not yet match the cleaner target model where Supervisor becomes the primary host-local runtime authority for external execution workloads.

Code anchors:

- `backend/app/supervisor/service.py`
- `backend/app/system/mqtt/runtime_boundary.py`

### Gap 5: Local admission exists, but local runtime policy enforcement is still shallow

Status: Partially implemented

Supervisor already exposes host admission context using CPU and memory pressure heuristics.

Missing pieces relative to the draft include:

- per-runtime quota enforcement
- richer restart/backoff policy
- broader placement policy
- generalized host-local execution policy for real Nodes

Code anchor:

- `backend/app/supervisor/service.py`

### Gap 6: Real Node lifecycle realization is still intent-only

Status: Partially implemented

Supervisor now tracks action intent and runtime freshness for real Nodes, but it does not yet act as a full executor for real Node processes or containers.

Current real Node lifecycle behavior:

- registration is implemented
- heartbeat is implemented
- freshness is implemented
- start/stop/restart action intent is implemented

Still missing relative to the draft:

- generalized local executor ownership for real Node processes
- direct process/container control for those runtimes
- richer restart and backoff semantics

Code anchors:

- `backend/app/supervisor/service.py`
- `backend/app/supervisor/runtime_store.py`

## Current Architecture Assessment

Status: Implemented

The current Supervisor is best described as:

- host monitor
- standalone addon runtime controller
- selected host-local runtime owner
- compatibility boundary for host-local runtime information
- contract-level registrar and freshness authority for real Nodes

It is not yet the full machine-side runtime authority envisioned by the architecture draft.

## Recommended Transition Milestones

### 1. Define a real Node-to-Supervisor contract

Status: Implemented

Implemented in this repository state:

- Node registration
- heartbeat
- runtime status updates
- start/stop/restart action intent for real Nodes

### 2. Separate standalone addon runtimes from real Nodes

Status: Not developed

Preserve standalone addons as a compatibility runtime class, but stop representing them as the same conceptual thing as real Nodes.

### 3. Move runtime truth for Nodes under Supervisor

Status: Not developed

Make Supervisor the source of truth for:

- local running/stopped/error state
- local health
- heartbeat freshness
- restart state
- host-local resource footprint

Keep Core as the source of truth for:

- trust
- onboarding approval
- governance
- capability registry
- policy

### 4. Make Core consume Supervisor runtime state

Status: Partially implemented

Core node registry views can now expose Supervisor runtime truth in read-only form, while trust and governance remain Core-owned.

### 5. Consolidate host-local external runtime ownership behind Supervisor

Status: Not developed

Shift machine-side external runtime realization toward Supervisor wherever that runtime is not a Core-internal embedded responsibility.

### 6. Expand local admission into real host-local policy enforcement

Status: Not developed

Add:

- per-runtime capacity checks
- richer restart policy
- resource ceilings
- runtime placement constraints

### 7. Cleanly document the transition state

Status: Partially implemented

Keep the documentation explicit about:

- current compatibility-era Supervisor behavior
- target Supervisor behavior
- remaining ownership migration work

## Suggested End-State Boundary

Status: Documented but not implemented

The target ownership split should look like this:

- Core:
  - trust
  - policy
  - capability registry
  - scheduling and orchestration
  - operator UI
  - global platform state
- Supervisor:
  - host resources
  - host-local runtime registry
  - Node lifecycle realization
  - process and container management
  - restart and recovery behavior
  - local runtime status truth
  - local admission and execution policy
- Nodes:
  - capability implementation
  - self-reported health and heartbeat
  - execution of external compute and functionality

## See Also

- [README.md](./README.md)
- [runtime-and-supervision.md](./runtime-and-supervision.md)
- [domain-models.md](./domain-models.md)
- [../Upgrades/synthia-core-supervisor-node-design.md](../Upgrades/synthia-core-supervisor-node-design.md)

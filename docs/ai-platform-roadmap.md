# Synthia Distributed AI Platform Roadmap

Status: Draft  
Last Updated: 2026-03-11  
Owner: Synthia Core / AI Node Architecture  

---

# Overview

Synthia is evolving into a **distributed AI execution platform** composed of:

- **Synthia Core** — governance, orchestration, policy authority
- **AI Nodes** — trusted execution environments for AI workloads
- **Addons / Services** — functional components integrated through the Synthia ecosystem
- **MQTT control plane** — discovery and event routing

The platform is built incrementally through structured phases.

Each phase introduces **one architectural capability layer**.

---

# Phase 1 — Node Discovery and Trust Establishment

Status: completed  
Last Updated: 2026-03-11 

---
## Objective

Allow AI Nodes to securely discover Synthia Core and establish a trusted relationship.

## Key Capabilities

- MQTT bootstrap discovery
- Node registration
- Operator approval workflow
- Trust token issuance
- Operational MQTT credentials
- Node trust-state persistence

## Node Lifecycle States Introduced

```

unconfigured
bootstrap_connecting
bootstrap_connected
core_discovered
registration_pending
pending_approval
trusted

```

## Core Responsibilities

- Advertise bootstrap payload
- Create onboarding sessions
- Manage operator approval flow
- Issue node trust activation payload
- Register node identity

## Deliverables

- Secure onboarding flow
- Trusted node identity
- Operational MQTT credentials

---

# Phase 2 — Capability Declaration and Governance

Status: in-development  
Last Updated: 2026-03-11 
 
---

## Objective

Allow trusted nodes to declare what they can do and receive governance rules from Core.

## Key Capabilities

- Node capability declaration
- Capability validation
- Capability profile registry
- Governance baseline issuance
- Node operational readiness evaluation

## New Lifecycle States

```

capability_setup_pending
operational
degraded

```

## `capability_setup_pending` Contract (Golden)

While in `capability_setup_pending`, node/runtime and operators should treat this as a blocked pre-operational state.

Required readiness data:
- trusted identity context is valid (`trust_status=trusted`)
- provider selection is configured for declaration
- capability declaration status is explicit (`missing|declared|accepted`)
- governance sync status is explicit (`pending_capability|pending|issued`)
- blocking reasons are visible via status fields and related error context

Transition criteria:
- `capability_setup_pending -> operational` only when:
  - `capability_status=accepted`
  - `governance_status=issued`
  - `operational_ready=true`
- Any failure in declaration/governance sync keeps state non-operational and may surface degraded indicators.

## Setup-State Polling Contract

Canonical polling endpoint for setup progression:
- `GET /api/system/nodes/operational-status/{node_id}`

Required payload fields for setup UI/state machine:
- `lifecycle_state`
- `trust_status`
- `capability_status`
- `governance_status`
- `operational_ready`
- `active_governance_version`
- `last_governance_issued_at`
- `last_governance_refresh_request_at`
- `last_telemetry_timestamp`

## Node Responsibilities

- Declare supported task families
- Declare enabled providers
- Declare environment hints
- Sync governance bundle

## Core Responsibilities

- Validate capability manifests
- Create capability profiles
- Issue governance bundles
- Track node operational readiness

## Deliverables

- Nodes become **known compute resources**
- Core understands **cluster capabilities**

---

# Phase 3 — AI Task Governance and Execution Gateway

## Objective

Introduce a **controlled execution model** for AI tasks.

This phase introduces **prompt governance and execution rules**.

## Key Capabilities

- Prompt registration
- Prompt probation period
- Prompt budget controls
- Execution policies
- Task routing

## Prompt Governance Concepts

Each prompt includes:

- expiration rules
- budget limits
- probation status
- execution scope
- provider constraints

Example prompt policy:

```

budget_daily: $2
budget_monthly: $20
probation_period: 30 executions
expires_after: 90 days

```

## Core Responsibilities

- Prompt registry
- Prompt approval workflow
- Budget enforcement
- Task routing decisions

## Node Responsibilities

- Execute approved prompts
- Enforce execution constraints
- Report execution telemetry

## Deliverables

- Safe AI execution
- Cost control
- Prompt lifecycle management

---

# Phase 4 — Distributed AI Scheduling and Resource Coordination

## Objective

Transform nodes into a **distributed AI compute cluster**.

## Key Capabilities

- Task scheduling
- Node resource awareness
- Multi-node workload distribution
- Priority queues
- Load balancing

## Node Resource Signals

Nodes may advertise:

```

CPU capacity
GPU presence
memory class
execution concurrency limits

```

## Core Responsibilities

- Task queue management
- Node selection
- Load distribution
- Failure recovery

## Deliverables

- Distributed AI compute grid
- Scalable execution environment

---

# Phase 5 — Autonomous AI Service Ecosystem

## Objective

Enable **autonomous AI services** operating across the Synthia platform.

This phase introduces high-level AI behaviors.

## Key Capabilities

- Service-driven AI agents
- Event-driven automation
- Cross-node workflows
- Autonomous task orchestration
- AI service lifecycle management

## Example Services

```

vision-classification service
email-intelligence service
automation-assistant service
document-analysis service

```

## Core Responsibilities

- Service registry
- Service permissions
- Workflow orchestration

## Node Responsibilities

- Execute service workloads
- Maintain service state
- Provide execution telemetry

## Deliverables

- Intelligent service platform
- Autonomous AI capabilities

---

# Architecture Summary

```

Phase 1
Node Discovery & Trust
↓
Phase 2
Capability Declaration
↓
Phase 3
Prompt Governance
↓
Phase 4
Distributed Scheduling
↓
Phase 5
Autonomous AI Services

```

---

# Platform Design Principles

## Core as Authority

Synthia Core remains the **source of truth** for:

- trust
- governance
- policy
- orchestration

Nodes **never self-authorize capabilities**.

---

## Nodes as Execution Engines

AI Nodes provide:

- AI provider integration
- compute resources
- runtime execution

Nodes **do not decide policy**.

---

## MQTT as Control Plane

MQTT is used for:

- discovery
- telemetry
- control signals

Sensitive data flows through **trusted API channels**.

---

## Safety First

The platform enforces:

- prompt approval
- execution limits
- budget constraints
- governance policies

This prevents uncontrolled AI behavior.

---

# Long-Term Vision

Synthia becomes a **distributed personal AI infrastructure** where:

- Core governs policy
- Nodes provide compute
- Services provide intelligence
- Users remain in control

The result is a **modular, extensible AI platform** that can scale from:

```

one home server
to
a distributed AI compute network

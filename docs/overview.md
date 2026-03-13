
# Synthia Platform Overview

Synthia is a modular automation and AI platform designed for home and edge environments.  
It provides a unified control plane for automation services, AI capabilities, device integrations, and distributed nodes.

At the center of the platform is **Synthia Core**, which acts as the system authority and orchestration layer.

The platform is designed to support:

- single-host deployments
- multi-service local environments
- distributed edge nodes
- extensible addon ecosystems

---

# Core Concepts

Synthia is built around a small set of core concepts.

Understanding these components explains how the entire platform operates.

## Synthia Core

Synthia Core is the **control-plane service** for the platform.

Core is responsible for:

- hosting the main API
- serving the administration UI
- managing addons
- coordinating nodes
- providing scheduler and worker infrastructure
- managing MQTT policy and runtime messaging
- aggregating telemetry and health signals

Core is the **authority for platform state**.

All addons and nodes ultimately interact with the platform through Core.

---

## Addons

Addons extend the capabilities of the platform.

Two addon models exist.

### Embedded Addons

Embedded addons run directly inside the Core runtime.

Characteristics:

- share the Core process
- mount routes into the Core API
- integrate directly into the UI
- managed entirely by Core

Examples:

- platform services
- lightweight integrations
- internal tools

---

### Standalone Addons

Standalone addons run as **separate runtime services**.

They are supervised by the **Synthia Supervisor**.

Characteristics:

- independent runtime process
- lifecycle managed by Core
- installed through the addon platform
- communicate with Core through APIs or MQTT

Examples:

- large integrations
- compute services
- external platform bridges

---

## Nodes

Nodes are **external trusted systems** that connect to Synthia Core.

Nodes expand the platform beyond a single machine.

Nodes may provide:

- AI inference
- device integrations
- automation engines
- external compute resources

Nodes connect to Core and:

- register with a trust model
- declare capabilities
- receive governance configuration
- publish telemetry

Examples:

- AI nodes
- vision processing nodes
- hardware integration nodes

---

## MQTT Platform Layer

MQTT provides the **internal messaging backbone** of the Synthia platform.

MQTT is used for:

- event propagation
- notifications
- telemetry
- service coordination
- node communication

Core defines the **topic structure and messaging policies** used by the platform.

---

## Scheduler and Workers

The scheduler subsystem manages **deferred and asynchronous work**.

Responsibilities include:

- scheduled jobs
- queue dispatch
- worker coordination
- execution tracking
- job history

Workers execute jobs produced by the scheduler.

---

## Supervisor

The Supervisor subsystem manages **standalone runtime services**.

Responsibilities include:

- service lifecycle management
- desired vs runtime reconciliation
- container or compose supervision
- restart and health behavior

This allows Core to manage services without directly hosting them.

---

# Platform Architecture

At a high level, the platform looks like this:

```

```
            ┌─────────────────────────┐
            │      Synthia UI         │
            │       (React)           │
            └──────────┬──────────────┘
                       │
            ┌──────────▼───────────┐
            │      Synthia Core    │
            │  API + Runtime Auth  │
            └──────────┬───────────┘
                       │
     ┌─────────────────┼─────────────────┐
     │                 │                 │
```

┌─────▼─────┐     ┌─────▼─────┐     ┌─────▼─────┐
│ Scheduler │     │  MQTT     │     │ Addons    │
│ Workers   │     │ Platform  │     │ Platform  │
└─────┬─────┘     └─────┬─────┘     └─────┬─────┘
│                 │                 │
│                 │                 │
│           ┌─────▼─────┐           │
│           │ Supervisor│           │
│           └─────┬─────┘           │
│                 │                 │
│        Standalone Addons          │
│                                   │
│                                   │
└───────────────┬───────────────────┘
│
External Nodes

```

---

# Platform Design Goals

Synthia is designed with the following goals.

### Modular Architecture

Subsystems should be loosely coupled and replaceable.

### Distributed Capability

The platform should support both single-machine and distributed deployments.

### Extensibility

New capabilities should be added through addons and nodes.

### Clear Platform Authority

Core acts as the authoritative control-plane for configuration, governance, and state.

### Operational Transparency

Operators should be able to inspect platform state, health, and behavior through the UI and APIs.

---

# Documentation Structure

Core documentation is organized by subsystem.

Examples:

```

docs/
overview.md
core/
mqtt/
scheduler/
supervisor/
addons/
nodes/
api/

```

Each subsystem contains its own architecture notes, contracts, and reference documentation.

---

# Related Repositories

The Synthia ecosystem may include additional repositories implementing nodes or standalone addons.

Examples include:

- AI Node implementations
- Vision processing services
- platform integrations
- external automation nodes

These repositories provide **implementation details**, while Core documentation defines the **platform contracts and architecture**.

---

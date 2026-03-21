# Hexe Core

Hexe AI is a modular automation and AI platform designed for home and
edge environments.\
**Hexe Core** is the central control‑plane service that orchestrates
the platform --- providing APIs, UI, scheduling, MQTT authority, addon
lifecycle management, and node integration.

This repository contains the main runtime responsible for operating and
coordinating the Hexe AI ecosystem.

Compatibility note: active MQTT topic roots now use `hexe/...`. API route paths, Python modules, and systemd unit filenames still retain their existing internal identifiers.

------------------------------------------------------------------------

# What Is Hexe Core?

Hexe Core is the central service responsible for:

-   booting the platform
-   hosting the main APIs
-   serving the administration UI
-   coordinating runtime state
-   managing addons and external nodes
-   providing shared infrastructure services

Core acts as the **platform authority** that other components connect
to.

------------------------------------------------------------------------

# What Does It Include?

The repository currently contains the following major components.

### FastAPI Backend

Located in:

    backend/app/

Responsibilities:

-   primary API surface
-   runtime state authority
-   addon registry and lifecycle management
-   node onboarding and governance
-   scheduler orchestration
-   MQTT control-plane services
-   telemetry and health aggregation

------------------------------------------------------------------------

### React Frontend

Located in:

    frontend/

Responsibilities:

-   platform administration UI
-   system status dashboards
-   addon store and management
-   configuration and diagnostics tools

------------------------------------------------------------------------

### MQTT Platform Services

Embedded MQTT support provides:

-   platform notification routing
-   runtime reconciliation signals
-   internal service messaging
-   node communication
-   telemetry collection

Core acts as the **authority for MQTT topic structure and policy**.

------------------------------------------------------------------------

### Scheduler

Located under:

    backend/app/system/scheduler/

Responsibilities:

-   job queue management
-   capacity-aware dispatch
-   leases and execution tracking
-   completion history
-   scheduling policies

------------------------------------------------------------------------

### Workers

Worker helpers located under:

    backend/app/system/worker/

Responsibilities:

-   Supervisor-owned host-local task execution helpers during migration
-   runtime worker coordination
-   scheduled job execution helpers

------------------------------------------------------------------------

### Supervisor

Standalone runtime management code:

    backend/synthia_supervisor/

Responsibilities:

-   standalone addon runtime supervision
-   compose-based service orchestration
-   desired vs runtime state reconciliation
-   host-local lifecycle and resource authority

------------------------------------------------------------------------

### Extension Platform

Hexe AI currently documents three extension/runtime categories.

**Embedded Addons**

-   run inside the Core runtime
-   mounted directly into API and UI

**Standalone Addons**

-   separate runtime units
-   managed by the Supervisor
-   lifecycle handled by Core

**External Nodes**

-   trusted external systems
-   capability and execution surfaces outside Core
-   the canonical model for new external functionality

Responsibilities include:

-   discovery
-   registry state
-   install / update / uninstall flows
-   UI embedding
-   store integration

------------------------------------------------------------------------

### Nodes

Nodes are **external trusted systems** that integrate with Hexe Core.

Nodes can:

-   declare capabilities
-   receive governance/configuration
-   publish telemetry
-   provide AI providers or other platform services

Examples include:

-   AI nodes
-   device integration nodes
-   external automation engines

------------------------------------------------------------------------

# Repository Structure

High-level layout of this repository:

    backend/                 FastAPI backend and platform services
    frontend/                React admin UI
    backend/synthia_supervisor/  Standalone runtime supervision components
    backend/app/system/      Scheduler, workers, MQTT services
    scripts/                 Bootstrap and development helpers
    systemd/user/            User service templates
    docs/                    Platform documentation

------------------------------------------------------------------------

# Installation and Development

## Local Development

Backend dependencies are defined in:

    backend/requirements.txt

Frontend dependencies are defined in:

    frontend/package.json

Typical development flow:

``` bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Start backend:

``` bash
.venv/bin/python -m uvicorn app.main:app --reload --port 9001
```

In a second terminal:

``` bash
cd frontend
npm install
npm run dev -- --port 80
```

Optional helper script:

    scripts/dev.sh

This script prints the expected development commands and loads
development helper environment variables from:

    .config/hexe/admin.env

------------------------------------------------------------------------

## Bootstrap Installation

The repository provides a bootstrap installer:

``` bash
./scripts/bootstrap.sh --dir <install_dir> --install
```

The bootstrap script performs:

-   repository clone or update
-   backend virtual environment setup
-   backend dependency installation
-   frontend dependency installation
-   addon frontend synchronization
-   user systemd service installation
-   frontend API configuration
-   service enable + startup

Installed services include:

-   `synthia-backend.service`
-   `synthia-frontend-dev.service`
-   supervisor runtime services
-   update helpers

------------------------------------------------------------------------

# Platform Extension Model

Hexe AI supports three extension models:

**Embedded Addons**\
Run directly inside the Core runtime.

**Standalone Addons**\
Separate runtime services managed by the Supervisor.

**External Nodes**\
Trusted external systems that connect to Core and declare capabilities.

This allows the platform to scale from a single host to a distributed
edge architecture.

------------------------------------------------------------------------

# Documentation

The detailed platform documentation is located under:

    docs/

Key entry points:

### Platform Overview

-   docs/index.md
-   docs/overview.md

### Core Platform

-   docs/architecture.md
-   docs/core/api/core-platform.md
-   docs/supervisor/runtime-and-supervision.md

### MQTT Platform

-   docs/mqtt/mqtt-platform.md
-   docs/mqtt/topics.md
-   docs/mqtt/notifications.md

### Addon Platform

-   docs/addons/addon-platform.md
-   docs/addons/addon-lifecycle.md

### API and Development

-   docs/core/api/api-reference.md
-   docs/development-guide.md

### Operations

-   docs/operators-guide.md

------------------------------------------------------------------------

# Related Repositories

Hexe Core is part of the larger Hexe AI ecosystem which may include:

-   AI Nodes
-   Vision services
-   standalone addon compatibility runtimes
-   external nodes
-   platform integrations

Core acts as the **platform authority and orchestration layer** for
these components.

------------------------------------------------------------------------

# License

Project license and usage terms are defined in the repository root.

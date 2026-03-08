# Synthia Standalone Addon Specification

Last Updated: 2026-03-08 13:08 US/Pacific

Version: 0.1 (development phase)

This document defines the **structure, packaging, and runtime
expectations** for standalone addons managed by the Synthia Supervisor.

------------------------------------------------------------------------

## Documentation Contract

This specification reflects the **actual runtime behavior supported by
the current Synthia Supervisor implementation**.

If a capability, safeguard, validation rule, or runtime behavior is
**not explicitly documented here as implemented**, it must be assumed to
be **not developed / not guaranteed by the current standalone addon
runtime**.

Features may be introduced later but must not be assumed unless
documented.

------------------------------------------------------------------------

## Enforcement Boundary

This specification distinguishes between:

1. behavior guaranteed by the supervisor runtime
2. behavior produced by the default Core-authored install flow
3. behavior not currently enforced for custom compose files

If a restriction is not enforced by the supervisor itself, it must not
be described as a universal runtime prohibition.

This boundary is important because the supervisor may reuse an existing
`docker-compose.yml` without rewriting policy defaults.

------------------------------------------------------------------------

# 1. Overview

Standalone addons are containerized services managed by the **Synthia
Supervisor**.

They are installed through the **Core Store system**, staged locally as
artifacts, and then reconciled into running containers.

High-level lifecycle:

Catalog ↓ Core install ↓ artifact staged ↓ desired.json written ↓
Supervisor reconcile ↓ docker compose up ↓ addon running

Reconciliation model:

Supervisor reconciliation is polling-based (interval-driven), not
event-driven.

Architecture overview:

  --------- -----
  Catalog   

  --------- -----

      |
      v

  --------- -----
  Core      
  install   

  --------- -----

      |
      v

desired.json + addon.tgz \| v +-------------+ \| Supervisor \| \|
reconcile \| +------+------+ \| v +-------------+ \| Docker \| \|
container \| +-------------+

------------------------------------------------------------------------

# 2. Addon Artifact Structure

Standalone addons are distributed as:

addon.tgz

The archive must extract into a valid **Docker build context**.

Example structure:

addon.tgz │ └── extracted/ ├── Dockerfile ├── app/ ├── requirements.txt
└── additional project files

Requirements:

  Component             Requirement
  --------------------- -------------
  Dockerfile            Required
  Valid build context   Required
  Application runtime   Required

Supervisor builds containers using:

build: \<versions/`<version>`{=html}/extracted/\>

Therefore the artifact **must contain a valid Dockerfile**.

------------------------------------------------------------------------

# 3. Dockerfile Requirements

Addons must include a valid Dockerfile.

Example minimal Python addon:

FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install -r requirements.txt

CMD \["python", "main.py"\]

Requirements:

• Must build successfully via Docker\
• Must start a long-running process\
• Must not require interactive input

------------------------------------------------------------------------

# 4. Environment Variables

Supervisor writes environment variables into:

runtime.env

Addon containers **must read configuration via environment variables**.

Expected variables in the standard Core-authored install flow:

SYNTHIA_ADDON_ID SYNTHIA_SERVICE_TOKEN CORE_URL

Example usage:

os.environ\["SYNTHIA_ADDON_ID"\]

Environment variables are **not expanded by the supervisor**.

Docker Compose performs runtime substitution.

Supervisor guarantee boundary:

The supervisor itself only guarantees environment variables present in
`desired.config.env`.

`SYNTHIA_SERVICE_TOKEN` is injected only when present in the supervisor
process environment.

Status:

Env-file generation from desired config: Implemented\
Universal required variable set at supervisor layer: Not developed

------------------------------------------------------------------------

# 5. Networking Model

Containers run in a dedicated Docker network defined in desired.json.

Default network:

synthia_net

Port exposure rules:

  bind_localhost   Behavior
  ---------------- ----------------
  true             bind 127.0.0.1
  false            bind 0.0.0.0

Example port mapping:

127.0.0.1:9002 → container:9002

If no ports are defined:

• the addon runs internal-only

------------------------------------------------------------------------

# 6. Port Configuration

Ports are declared through desired.json runtime configuration.

Example:

{ "ports": \[ { "host": 9002, "container": 9002, "proto": "tcp" } \] }

Addons must listen on the container port defined here.

------------------------------------------------------------------------

# 6.1 Compose Project Naming

For Core-authored standalone installs, if runtime project name is not
explicitly provided, Core defaults `runtime.project_name` to:

`synthia-addon-<addon_id>`

If a project name is explicitly provided in runtime overrides, Core
normalizes it to a Docker Compose-safe value (lowercase; only
alphanumeric, `_`, `-`; must start with alphanumeric).

------------------------------------------------------------------------

# 6.2 Desired Update and Rebuild Contract

Current implementation (code-verified):

- Addons do not notify supervisor directly.
- Core Store writes `desired.json` (atomic replace).
- Supervisor picks up that change on the next polling reconcile cycle.

What triggers rebuild/recompose today:

- Changing `pinned_version` to a new version directory triggers a new
  extract/build/reconcile path.
- Core also writes `desired_revision`; if unchanged for same running
  version, supervisor no-ops.
- Set `force_rebuild=true` with a new `desired_revision` when an
  operator explicitly wants rebuild/recreate semantics even without
  compose-input changes.
- For same-version updates, compose-impacting desired changes
  (`network`, `bind_localhost`, `ports`, `cpu`, `memory`) trigger
  compose regeneration/reconcile.
- Optional docker services are controlled through
  `desired.enabled_docker_groups`.

Addon author guidance:

- Put exposed ports in addon `manifest.json` `runtime_defaults.ports`
  (and optional `runtime_defaults.bind_localhost`) so Core can write
  desired runtime intent correctly.
- For runtime topology changes that require a different compose file,
  provide override files named `docker-compose.group-<group>.yml` in the
  extracted addon artifact and enable those groups through desired state.

Not developed:

- Direct addon-originated supervisor notify/rebuild API.

------------------------------------------------------------------------

# 6.3 Optional Docker Group Architecture

Current implementation pattern:

- Base deployment:
  - `versions/{version}/docker-compose.yml`
- Optional group overrides (artifact-provided):
  - `versions/{version}/extracted/docker-compose.group-<group>.yml`
- Desired control (Core-written):
  - `desired.json` -> `enabled_docker_groups: ["group_a", ...]`
- Supervisor responsibility:
  - include base compose file always
  - include each group override file that exists
  - track missing requested groups as failed
  - run compose with `--remove-orphans` so disable transitions remove
    containers no longer part of requested topology

Runtime reporting:

- `runtime.json.requested_docker_groups`
- `runtime.json.active_docker_groups`
- `runtime.json.failed_docker_groups`
- `runtime.json.compose_files_in_use`

Example flow:

1. Install addon with no optional groups (`enabled_docker_groups=[]`).
2. Complete addon setup.
3. Core updates desired with `enabled_docker_groups=["broker"]`.
4. Supervisor reconciles using base + `docker-compose.group-broker.yml`.
5. Runtime state reports `requested=["broker"]`, `active=["broker"]`,
   `failed=[]`.

------------------------------------------------------------------------

# 7. Addon Identity

Identity variables are expected in the standard Core-authored install
flow.

Typical identity variables:

SYNTHIA_ADDON_ID SYNTHIA_SERVICE_TOKEN CORE_URL

Addons should use these for:

• authentication with Core • service registration • API calls

Supervisor guarantee boundary:

The supervisor itself only guarantees values present in
`desired.config.env` (plus optional `SYNTHIA_SERVICE_TOKEN` injection
when available in supervisor process environment).

------------------------------------------------------------------------

# 8. Logging

Addons should log to:

stdout stderr

Docker captures container logs which can be inspected via:

docker logs `<container>`{=html}

Structured logging is recommended but not required.

------------------------------------------------------------------------

# 9. Health Checks

Supervisor currently **does not perform HTTP health checks**.

Core runtime aggregation adds optional service probing for standalone
addons:

- probe endpoint: `GET /api/addon/health`
- probe runs only when runtime aggregation health probing is enabled and
  a published TCP port is available
- probing is optional and disabled by default (`SYNTHIA_RUNTIME_HEALTH_PROBE_ENABLED`)
- missing endpoint (`404`) results in health state `unknown`

Health model exposed by Core runtime aggregation:

- `runtime_state`: runtime/container execution state
- `health_status`: service-level health (`healthy|unhealthy|unknown`)

Addons may expose:

GET /api/addon/meta\
GET /api/addon/health

------------------------------------------------------------------------

# 10. Security Model

Standalone addons are **trusted workloads**.

Supervisor does not sandbox containers.

Isolation is provided only by Docker runtime controls.

Supervisor compose defaults include:

privileged: false\
security_opt: no-new-privileges

Addons must be considered **trusted code**.

------------------------------------------------------------------------

# 11. Resource Limits

Supervisor-generated compose files now support optional resource limits:

• `cpus` from `desired.runtime.cpu`\
• `mem_limit` from `desired.runtime.memory`

These limits are optional and only applied when provided in desired
runtime intent.

Not developed:

• IO limits\
• pids limits\
• advanced policy validation for resource-unit formats

------------------------------------------------------------------------

# 12. Addon Responsibilities

Addon authors are responsible for:

  Responsibility                  Status
  ------------------------------- -------------
  Provide Dockerfile              Required
  Accept env configuration        Required
  Handle startup errors           Recommended
  Log to stdout/stderr            Recommended
  Expose optional API endpoints   Optional

------------------------------------------------------------------------

# 13. Generated Template Defaults vs Supervisor Enforcement

Supervisor-generated compose templates include security defaults.

Generated template defaults include:

• `privileged: false`\
• `security_opt: no-new-privileges:true`\
• no host network mode setting\
• no filesystem mounts

These defaults apply only to supervisor-generated compose templates.

If a version already includes a `docker-compose.yml` file, the
supervisor does not rewrite it and therefore does not enforce these
defaults.

Supervisor does not expose a container exec API.

Status:

Generated template defaults: Implemented\
Universal runtime enforcement: Not developed\
Supervisor exec API: Not developed

------------------------------------------------------------------------

# 14. Development Policy

During active development:

• artifact signature verification is disabled\
• artifact checksum validation is disabled\
• catalog trust enforcement is disabled

Verification utilities exist but are not used by the supervisor
reconcile path.

This behavior is **intentional during development**.

------------------------------------------------------------------------

# 15. Future Extensions (Not Implemented)

Potential future capabilities:

• container health monitoring\
• automatic rollback\
• resource quotas\
• supervisor metrics endpoint\
• addon permission model\
• catalog trust enforcement

Status: Not developed

------------------------------------------------------------------------

# End of Specification

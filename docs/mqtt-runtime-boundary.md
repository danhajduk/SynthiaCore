# MQTT Broker Runtime Boundary (Embedded)

Last Updated: 2026-03-10 02:57 US/Pacific

## Boundary Definition

Embedded MQTT broker runtime is treated as platform infrastructure and separated from addon registry/proxy flows.

Core-side boundary interface:
- `backend/app/system/mqtt/runtime_boundary.py`
  - `ensure_running`
  - `health_check`
  - `reload`
  - `controlled_restart`
  - `get_status`

## Degraded-State Semantics

Runtime status contract:
- `state` (`running` / `stopped` or provider-specific equivalent)
- `healthy` boolean
- `degraded_reason` optional reason string
- `checked_at` timestamp

## Implementation Note

Current implementation in repo:
- `InMemoryBrokerRuntimeBoundary` provides deterministic behavior for boundary integration/testing.
- `DockerMosquittoRuntimeBoundary` (also exposed via legacy alias `MosquittoProcessRuntimeBoundary`) is the active local broker runtime provider:
  - container image: `eclipse-mosquitto:2` (override: `SYNTHIA_MQTT_DOCKER_IMAGE`)
  - container name: `synthia-mqtt-broker` (override: `SYNTHIA_MQTT_DOCKER_CONTAINER`)
  - published ports:
    - main listener: `SYNTHIA_MQTT_PORT` (default `1883`) -> container `1883`
    - bootstrap listener: `SYNTHIA_MQTT_BOOTSTRAP_PORT` (default `1884`) -> container `1884`
  - startup command: `docker run ... mosquitto -c <live_dir>/broker.conf`
  - restart policy: `unless-stopped`
  - reload: `docker kill --signal HUP <container>`
  - stop: `docker rm -f <container>`

## Docker Runtime Contract

Mount contract (host path -> same path in container):
- `var/mqtt_runtime/live` -> mounted read-only; authoritative rendered broker/auth/ACL configs from Core apply pipeline
- `var/mqtt_runtime/data` -> mounted read-write for broker persistence
- `var/mqtt_runtime/logs` -> mounted read-write for broker logs

Behavior contract:
- Core remains the authority for rendered files and runtime lifecycle actions.
- Generated runtime files under `var/mqtt_runtime/*` are runtime artifacts, not source-of-truth policy definitions.
- `ensure_running` is idempotent:
  - healthy running container -> no-op success
  - stopped/exited container -> remove/recreate path
- `health_check` requires both:
  - container running state
  - broker TCP reachability at configured host/port

## Runtime Artifact Pipeline

Authoritative runtime artifact directories:

```text
var/mqtt_runtime/
  staged/
    broker.conf
    listeners.conf
    auth.conf
    acl.conf
    acl_compiled.conf
    passwords.conf
  live/
    broker.conf
    listeners.conf
    auth.conf
    acl.conf
    acl_compiled.conf
    passwords.conf
  data/
  logs/
```

Pipeline ordering:
1. Core persists selected setup settings (`mqtt.mode`, host/port/auth/client options).
2. Reconciler renders broker artifacts.
3. Apply pipeline writes rendered files into `var/mqtt_runtime/staged/`.
4. Apply pipeline atomically promotes staged artifacts into `var/mqtt_runtime/live/`.
5. Runtime boundary reload/restart path verifies runtime health.
6. Router/runtime flow ensures runtime running and finalizes setup state.
7. Bootstrap topic publish runs only after runtime reports healthy.

Startup bootstrap:
- Core startup now ensures runtime directory structure exists before runtime boundary/pipeline wiring:
  - `var/mqtt_runtime/`
  - `var/mqtt_runtime/staged/`
  - `var/mqtt_runtime/live/`
  - `var/mqtt_runtime/data/`
  - `var/mqtt_runtime/logs/`
- Runtime boundary also normalizes permissions before launch:
  - `data/` and `logs/` are set writable (`0777`) for container process writes.
  - required live runtime files (`broker.conf`, `acl_compiled.conf`, `passwords.conf`, etc.) are normalized to readable mode (`0644`).

Runtime preflight expectations:
- Runtime start validates required live files before attempting Docker start:
  - `live/broker.conf`
  - `live/acl_compiled.conf`
  - `live/passwords.conf`
- If missing, runtime reports `degraded_reason=config_missing:*` with:
  - expected live broker path
  - staged broker existence flag
  - live directory existence flag
  - missing file list
  - remediation suggestion (`run_setup_apply_or_runtime_rebuild`)

## Runtime Control API Surface

Core exposes runtime-control routes that use this boundary:
- `GET /api/system/mqtt/runtime/health` -> `health_check`
- `POST /api/system/mqtt/runtime/start` -> `ensure_running`
- `POST /api/system/mqtt/runtime/stop` -> `stop`
- `POST /api/system/mqtt/runtime/rebuild` -> reconcile path + health verification (or `controlled_restart` fallback)
- `POST /api/system/mqtt/runtime/init` -> reconcile path + `ensure_running`

All runtime control actions emit authority audit events under `event_type=mqtt_runtime_control`.

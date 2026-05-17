# Hexe Supervisor Docs

This is the canonical entrypoint for Hexe Supervisor documentation in the `Core -> Supervisor -> Nodes` structure.

## Status

Status: Implemented

Supervisor currently spans:

- `backend/synthia_supervisor/`
- `backend/app/system/runtime/`
- `backend/app/supervisor/`
- `backend/app/supervisor/server.py`
- `systemd/user/hexe-supervisor-api.service.in`

Supervisor API routes are served by the standalone Supervisor service rather than the Core process.

## Current Responsibilities

- host monitoring through `HostResourceSummary`, `SupervisorHealthSummary`, and `SupervisorRuntimeSummary`
- host-local process/container resource sampling for Supervisor-visible `pid`, `systemd_unit`, `container_name`, and nested runtime service/container metadata
- admission context reporting through `GET /api/supervisor/admission`
- standalone addon lifecycle control through:
  - `GET /api/supervisor/nodes`
  - `POST /api/supervisor/nodes/{node_id}/start`
  - `POST /api/supervisor/nodes/{node_id}/stop`
  - `POST /api/supervisor/nodes/{node_id}/restart`
- core-hosted runtime supervision for Core services, addons, and aux containers through:
  - `POST /api/supervisor/core/runtimes/register`
  - `POST /api/supervisor/core/runtimes/heartbeat`
  - `GET /api/supervisor/core/runtimes`
  - `GET /api/supervisor/core/runtimes/{runtime_id}`
  - `POST /api/supervisor/core/runtimes/{runtime_id}/start`
  - `POST /api/supervisor/core/runtimes/{runtime_id}/stop`
  - `POST /api/supervisor/core/runtimes/{runtime_id}/restart`
- standalone runtime state reporting through:
  - `GET /api/supervisor/health`
  - `GET /api/supervisor/info`
  - `GET /api/supervisor/resources`
  - `GET /api/supervisor/runtime`
- boot loop status and manual trigger through:
  - `GET /api/supervisor/boot/status`
  - `POST /api/supervisor/boot/run`
- compose-based realization for host-local standalone addon workloads

## Service Configuration

The Supervisor API service reads its binding and transport settings from environment variables. These values are used by the standalone Supervisor API server and are safe to apply on Core or Node hosts.

Core uses a Supervisor API client with its own environment-backed settings (see [service-configuration.md](./service-configuration.md)).

- `HEXE_SUPERVISOR_TRANSPORT`: API transport mode. Supported values: `socket` or `http`. Default: `socket`.
- `HEXE_SUPERVISOR_BIND`: TCP bind host when `HEXE_SUPERVISOR_TRANSPORT=http`. Default: `127.0.0.1`.
- `HEXE_SUPERVISOR_PORT`: TCP port when `HEXE_SUPERVISOR_TRANSPORT=http`. Default: `57665`.
- `HEXE_SUPERVISOR_SOCKET`: Unix socket path when `HEXE_SUPERVISOR_TRANSPORT=socket`. Default: `/run/hexe/supervisor.sock`.
- `HEXE_SUPERVISOR_LOG_LEVEL`: Supervisor API server log level. Default: `INFO`.

## Install Modes

Supervisor can be installed as a first-party app independently from the Core runtime, or bundled beside Core.

### Standalone Supervisor

Standalone mode installs only the Supervisor daemon and Supervisor API services. It does not report to Core.

```bash
curl -fsSL https://raw.githubusercontent.com/danhajduk/HexeCore/main/core/scripts/install-supervisor.sh | bash -s -- --standalone
```

The default standalone Supervisor checkout location is `~/hexe/hexe/supervisor`.

### Remote Supervisor Joined To Core

Join-Core mode installs Supervisor on a host and configures remote reporting into Core.

First create a one-time enrollment token from Core with an admin session or admin token:

Open the Core Supervisor enrollment page in a browser:

```text
http://core-host:9001/system/supervisors/enrollment?supervisor_id=host-a&supervisor_name=Host%20A%20Supervisor
```

The page signs in with the normal Core admin session, creates the one-time token, and can copy either the token or a joined install command.

The same token can also be created directly through the API:

```bash
curl -fsS -X POST http://core-host:9001/api/system/supervisors/enrollment-tokens \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: $SYNTHIA_ADMIN_TOKEN" \
  -d '{"supervisor_id":"host-a","supervisor_name":"Host A Supervisor","ttl_seconds":900}'
```

Core returns `enrollment_token` and `one_time_token` with the same value. Pass that token to the remote host install command:

```bash
curl -fsSL https://raw.githubusercontent.com/danhajduk/HexeCore/main/core/scripts/install-supervisor.sh | bash -s -- \
  --join-core \
  --core-url http://core-host:9001 \
  --enrollment-token "$HEXE_SUPERVISOR_ENROLLMENT_TOKEN" \
  --supervisor-id host-a
```

`--join-core` requires `--core-url`, `--supervisor-id`, and either `--enrollment-token` or `--admin-token`. The preferred path is `--enrollment-token` (`--one-time-token` is accepted as an alias): the installer exchanges the one-time token with Core, stores only the returned Supervisor reporting token in `%h/.config/hexe/supervisor.env`, and sends future reports with `X-Supervisor-Token`.

`--admin-token` remains available for trusted local or compatibility installs, but it stores the Core admin token as the reporting credential.
The default joined Supervisor checkout location is also `~/hexe/hexe/supervisor`.

### Bundled With Core

Bundled-Core mode installs Supervisor beside a local Core checkout. This is the mode used by Core-host installs.

```bash
curl -fsSL https://raw.githubusercontent.com/danhajduk/HexeCore/main/core/scripts/install-supervisor.sh | bash -s -- \
  --bundled-core
```

The default bundled Core checkout location is `~/hexe/hexe/core`.

All modes prepare the backend Python runtime, install `hexe-supervisor.service` and `hexe-supervisor-api.service` as systemd user units, start both services by default, and verify the Supervisor API with `curl` over `/run/hexe/supervisor.sock`.

The installer writes `%h/.config/hexe/supervisor.env` with `HEXE_SUPERVISOR_INSTALL_MODE`. In join-Core mode it also writes the Core URL, reporting token, token kind, Supervisor ID/name/public URL values, and enables remote reporting. Core stores reported Supervisors behind `/api/system/supervisors`.

## Supervisor Enrollment Tokens

Status: Implemented

Core exposes a one-time enrollment flow for remote Supervisor installs:

- `POST /api/system/supervisors/enrollment-tokens`: admin-only endpoint that creates a short-lived one-time token. Tokens are stored hashed and may optionally be bound to a `supervisor_id`.
- `POST /api/system/supervisors/enroll`: unauthenticated exchange endpoint used by the installing host. It consumes the one-time token, registers the Supervisor, and returns a `reporting_token`.
- `POST /api/system/supervisors/register` and `POST /api/system/supervisors/heartbeat`: accept either the Core admin token in `X-Admin-Token` or the issued Supervisor reporting token in `X-Supervisor-Token`.

A migrated Node that installs the local Supervisor should receive or request the one-time enrollment token as part of the migration/onboarding handoff, pass it to `scripts/install-supervisor.sh` with `--enrollment-token`, and never persist the one-time token. The installer handles the exchange and writes the returned reporting token to the Supervisor environment file.

## Explicit Non-Goals

Status: Implemented

Supervisor does not own these areas in the current repository state:

- OS administration
- package management
- general service management outside Hexe-managed runtimes
- firewall and network policy management
- non-Hexe workload orchestration

## Future Expansion Path

Status: Not developed

Supervisor may grow into these areas later, but they are not implemented today:

- broader host-local workload supervision
- managed worker execution ownership
- richer reconciliation loops
- runtime backends beyond the current compose-based standalone path

## Included Docs

- [runtime-and-supervision.md](./runtime-and-supervision.md)
- [domain-models.md](./domain-models.md)
- [lifecycle-control.md](./lifecycle-control.md)
- [workload-admission.md](./workload-admission.md)
- [architecture-gap.md](./architecture-gap.md)
- [service-configuration.md](./service-configuration.md)

## See Also

- [../architecture.md](../architecture.md)
- [../addons/standalone-archive/README.md](../addons/standalone-archive/README.md)
- [../addons/addon-platform.md](../addons/addon-platform.md)

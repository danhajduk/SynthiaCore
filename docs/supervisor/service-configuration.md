# Supervisor Service Configuration

This document describes the environment-backed configuration contract for the standalone Supervisor API service.

## Runtime Service Configuration

Supervisor can listen on a Unix socket (default) or a TCP bind/port. These options are configured entirely through environment variables so the service can run on any host without code changes.

## Environment Contract

- `HEXE_SUPERVISOR_TRANSPORT`: API transport mode. Supported values: `socket` or `http`. Default: `socket`.
- `HEXE_SUPERVISOR_BIND`: TCP bind host when `HEXE_SUPERVISOR_TRANSPORT=http`. Default: `127.0.0.1`.
- `HEXE_SUPERVISOR_PORT`: TCP port when `HEXE_SUPERVISOR_TRANSPORT=http`. Default: `57665`.
- `HEXE_SUPERVISOR_SOCKET`: Unix socket path when `HEXE_SUPERVISOR_TRANSPORT=socket`. Default: `/run/hexe/supervisor.sock`.
- `HEXE_SUPERVISOR_LOG_LEVEL`: Supervisor API server log level. Default: `INFO`.

## Core Supervisor Client

Core talks to a remote Supervisor over the following environment-backed client settings.

- `HEXE_SUPERVISOR_API_TRANSPORT`: Client transport mode. Supported values: `socket`, `http`, or `disabled`. Default: `socket`.
- `HEXE_SUPERVISOR_API_BASE_URL`: Base URL for `http` transport. Default: `http://127.0.0.1:57665`.
- `HEXE_SUPERVISOR_API_SOCKET`: Unix socket path for `socket` transport. Default: `/run/hexe/supervisor.sock`.
- `HEXE_SUPERVISOR_API_TIMEOUT_S`: Client timeout (seconds). Default: `2.0`.
- `HEXE_CORE_RUNTIME_DECLARATIONS_JSON`: Optional JSON list (or `{ "items": [...] }`) of extra Core runtime declarations to register with the local Supervisor. Each entry should include `runtime_id`, `runtime_name`, `runtime_kind`, and `management_mode` plus optional state/metadata fields.

## Notes

- The Unix socket path is consistent across hosts to keep local Supervisor access predictable.
- When using `socket` transport, the Supervisor API server does not bind a TCP port.
- When using `http` transport, the Supervisor API server does not open a Unix socket.

## Health And Readiness Probes

- `GET /health` returns a basic liveness response for the Supervisor API service.
- `GET /ready` returns readiness based on `execution_host_ready` from the Supervisor admission summary and responds with `503` when the host is not ready.

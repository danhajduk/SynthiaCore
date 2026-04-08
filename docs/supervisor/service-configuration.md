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

## Notes

- The Unix socket path is consistent across hosts to keep local Supervisor access predictable.
- When using `socket` transport, the Supervisor API server does not bind a TCP port.
- When using `http` transport, the Supervisor API server does not open a Unix socket.

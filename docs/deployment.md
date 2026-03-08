# Deployment Documentation

Last Updated: 2026-03-07 16:08 US/Pacific

## Environments

Development-oriented setup is present in repo scripts and user systemd templates.

## Service Units

User service templates:
- `systemd/user/synthia-backend.service.in`
- `systemd/user/synthia-frontend-dev.service.in`
- `systemd/user/synthia-supervisor.service.in`
- `systemd/user/synthia-updater.service.in`

## Runtime Components

- Backend: FastAPI process from Python venv
- Frontend: dev service target for React/Vite workflow
- Supervisor: standalone addon reconcile worker (`python -m synthia_supervisor.main`)
- Updater: systemd-managed updater service

## Scripts and Operations

- `scripts/dev.sh`: development run helper
- `scripts/reload-all.sh`: daemon-reload + restart key units + updater trigger
- `scripts/bootstrap.sh`: bootstrap/setup helper
- `scripts/update.sh`: update workflow helper

## Networking and Ports

- Frontend dev origin defaults are configured in backend CORS (`localhost:5173`, `127.0.0.1:5173`).
- Standalone addon published ports are controlled by desired runtime settings and supervisor compose generation.

## Environment Variables

Commonly used:
- backend DB/state paths (`APP_SETTINGS_DB`, `APP_USERS_DB`, `SCHEDULER_HISTORY_DB`, `STORE_*`)
- standalone path override (`SYNTHIA_ADDONS_DIR`)
- supervisor poll/log settings (`SYNTHIA_SUPERVISOR_INTERVAL_S`, `SYNTHIA_SUPERVISOR_LOG_LEVEL`)
- supervisor retention policy (`SYNTHIA_SUPERVISOR_KEEP_VERSIONS`, default `3`, minimum effective `2`)

## Standalone Retention

Implemented behavior:
- Supervisor prunes older standalone version directories after successful reconcile.
- Active and previous versions are always retained.
- Additional recent versions are retained up to configured keep-count.
- Retention diagnostics are available from store status diagnostics endpoint (`/api/store/status/{addon_id}/diagnostics`).

## Rebuild/Restart

- Docs-only updates do not require binary rebuild.
- Service reload/restart uses `scripts/reload-all.sh` or direct systemctl user commands.

## Not Developed

- Fully documented production hardening profile in this repo
- End-to-end immutable deployment pipeline specification

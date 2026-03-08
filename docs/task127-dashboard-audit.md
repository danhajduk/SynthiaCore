# Task 127.1 Audit: Home Dashboard and Navigation

Date: 2026-03-07

## Frontend Data Sources (Current)

Home dashboard (`frontend/src/core/pages/Home.tsx`) currently reads:
- `GET /api/addons`
- `GET /api/system/stats/current`
- `GET /api/system/events?limit=8`
- `GET /api/system/repo/status`
- `GET /api/system/scheduler/status`
- `GET /api/system/mqtt/status`

Sidebar (`frontend/src/core/layout/Sidebar.tsx`) currently:
- uses a flat core route list (`Home`, `Store`, `Addons`, `Settings`, `Settings / Jobs`, `Settings / Metrics`, `Settings / Statistics`)
- appends dynamic addon nav entries
- restricts guest mode to `Home` only

## Backend Data Availability (Audit)

Available now:
- Core/backend health: `GET /api/health`
- Supervisor service state: `services.supervisor` in `GET /api/system/stats/current`
- Scheduler status: `GET /api/system/scheduler/status` (`active_leases`, `queue_depths`)
- MQTT status: `GET /api/system/mqtt/status` (`connected`, `last_error`, `last_message_at`, `message_count`)

Not available now:
- local network reachability status (gateway/LAN reachability checks)
- internet connectivity status (reachable/unreachable/degraded)
- internet speed snapshot (download/upload/latency with timestamp)

## Scope Readiness Outcome

Can proceed without backend additions:
- 127.3 (status widget expansion)
- 127.4 (MQTT visibility)
- 127.5 (scheduler visibility)
- 127.8 (degraded-state reasoning)
- 127.9 (sidebar categorization)
- 127.10 (guest/admin sidebar and status messaging)

Requires backend extension (127.11 candidate):
- 127.6 (network + internet health)
- 127.7 (internet speed snapshot)

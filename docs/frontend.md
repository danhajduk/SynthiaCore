# Frontend Documentation

Last Updated: 2026-03-07 18:36 US/Pacific

## Stack

- React + TypeScript
- React Router (`BrowserRouter`, route object model)
- Vite-based frontend build/dev workflow

## Entrypoints

- `frontend/src/main.tsx`: initializes theme and mounts app
- `frontend/src/App.tsx`: wraps app in `AdminSessionProvider`, applies route tree
- `frontend/src/core/router/routes.tsx`: route definitions and admin protection logic

## Route Structure

- Public:
  - `/` (Home)
- Admin-gated:
  - `/store`
  - `/addons`
  - `/settings`
  - `/settings/jobs`
  - `/settings/metrics`
  - `/settings/statistics`
  - dynamically loaded addon routes

## Core UI Areas

- Home:
  - operational dashboard for guest and admin
  - full-stack status widget driven by `GET /api/system/stack/summary`
  - subsystem pills: core, supervisor, mqtt, scheduler, workers, addons, network, internet
  - compact status row with scheduler/network/internet/speed visibility
    - speed label reflects speed sample status and timestamp freshness (`speedtest_cli`/`speedtest_ookla` active sample or `passive_estimate` fallback)
    - status/mini metrics render humanized capitalization for state values
    - top status card border matches status tone colors (success/warn/danger) with 2px border width
    - status mini value badges (`.home-mini-value`) use tone-matched 2px borders consistent with subsystem/status styling
    - login/session card is positioned directly beneath dashboard header
    - top-right updated badge uses 24h time format (`HH:MM:SS`)
  - degraded/attention reason details (expand/collapse)
  - Installed Addons panel
  - Recent Activity panel (platform events feed)
  - System Metrics panel (CPU/memory/disk + network/internet/speed status + throughput sample + network I/O/error counters)
    - CPU/Memory/Disk render as fill bars with percentage labels
  - shell header keeps only the main title text (legacy subtitle removed)
  - compact admin session strip (sign-in or sign-out state)
  - data refresh interval: 10s polling for dashboard cards (`/api/system/stack/summary` reads backend cached speed values only and does not trigger new speedtest runs)
- Store: catalog browsing, install actions, diagnostics and remediation UX
- Addons:
  - inventory and control-plane metadata/actions
  - admin-only uninstall action with explicit confirm/uninstall/success/failed states
  - standalone uninstall attempts surface remediation guidance instead of silent failure
  - successful uninstall triggers inventory + runtime refresh; sidebar addon links reconcile on next sidebar poll
- Settings: settings + jobs/metrics/statistics + admin controls
- Sidebar:
  - categorized admin navigation (`Home`, `Addons`, `Store`, `System`, `Addon UIs`)
  - guest navigation limited to `Home` with minimal guest footer messaging

## API Communication

- centralized client helpers in `frontend/src/core/api/client.ts`
- consumes backend endpoints for admin session, system stats, store, addons, scheduler

## Addon UI Integration

- dynamic route loading via `loadAddons.ts`
- addon routes wrapped in same admin-guard logic as core protected routes

## Styling and Theme

- theme token system under `frontend/src/theme/*`
- runtime theme init via `theme.ts`
- core layout/page CSS under `frontend/src/core/*/*.css`

## Not Developed

- Explicit offline-first frontend behavior
- Strict client-side feature flags framework

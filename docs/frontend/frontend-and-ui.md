# Frontend and UI

## Frontend Architecture

Status: Implemented

- Stack: React + TypeScript + React Router + Vite.
- Entrypoints:
  - `frontend/src/main.tsx`
  - `frontend/src/App.tsx`
  - `frontend/src/core/router/routes.tsx`
- Shell layout wraps route output and admin session context.

## Route and Page Model

Status: Implemented

- Public route: `/`.
- Onboarding approval route: `/onboarding/nodes/approve?sid=...&state=...` (login-gated within page flow).
- Admin-gated routes: `/store`, `/addons`, `/settings`, `/settings/jobs`, `/settings/metrics`, `/settings/statistics`, and addon routes.
- Addon frame routes: `/addons/:addonId` and `/addons/:addonId/:section`.

## Addon UI Conventions

Status: Implemented

- Addon UIs are rendered through Core iframe/proxy boundaries.
- MQTT addon setup-gate behavior redirects to setup section until setup is complete.
- Addon frame resolves embed target/runtime fallback from backend status APIs.

## Theming and Styling

Status: Implemented

- Theme tokens and CSS layers are maintained in `frontend/src/theme/*`.
- Core can inject shared theme tokens/classes into same-origin addon iframe documents.
- Shared addon styling guidance from prior theme docs is now consolidated here.

## Admin and Operator UX Patterns

Status: Implemented

- Home dashboard surfaces stack health and metrics.
- Settings organizes platform controls by subsystem.
- MQTT embedded UI includes overview/principals/users/runtime/audit/noisy-client pages.
- Node onboarding approval page requires normal admin session login before showing approval context.

### Home Status Tiles

Status: Implemented

- Location: Home dashboard status row (`frontend/src/core/pages/Home.tsx`, `frontend/src/core/pages/home.css`).
- Icon source: `lucide-react`.
- Tile set:
  - `Core` -> `Cpu`
  - `Supervisor` -> `ShieldCheck`
  - `MQTT` -> `Waypoints`
  - `Scheduler` -> `Clock3`
  - `Workers` -> `Cog`
  - `Addons` -> `Puzzle`
  - `Network` -> `Network`
  - `Internet` -> `Globe`
  - `AI Node` -> `BrainCircuit`
- Tile contract:
  - width `96px`
  - height `72px`
  - border radius `12px`
  - icon size `24px`
  - label font size `12px`, line-height `1`
  - icon/label gap `6px`
  - centered tile content
- Responsive behavior:
  - desktop: auto-fit fixed-width `96px` tiles
  - <=`920px`: 4 tiles per row
  - <=`520px`: 3 tiles per row
  - <=`360px`: 2 tiles per row
- Screenshot reference:
  - `docs/screenshots/home-status-tiles.md`

## Planned

Status: Planned

- Formal feature-flag framework across frontend capabilities.
- Offline-first UI behavior.

## Archived Legacy Behavior

Status: Archived Legacy

- Split UI/theme docs (`frontend.md`, `theme.md`, `ui-theme.md`, `addon-ui-styling.md`) were consolidated into this canonical document.

## See Also

- [API Reference](../fastapi/api-reference.md)
- [Addon Platform](../addon-embedded/addon-platform.md)
- [MQTT Platform](../mqtt/mqtt-platform.md)
- [Operators Guide](../operators-guide.md)

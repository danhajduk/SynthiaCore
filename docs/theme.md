# Theme System Contract for Addons

Last Updated: 2026-03-08 15:49 US/Pacific

## Scope

This document describes the currently implemented Core theme token system in `shared/theme/*`.

## Theme Loading

Implemented:

- Core imports `shared/theme/index.css` from `frontend/src/main.tsx`.
- `index.css` loads:
  - `tokens.css` (base tokens)
  - `base.css` (global elements)
  - `components.css` (`.card`, `.panel`, `.btn`, `.btn-primary`, `.badge`, `.pill`, `.form-input`, `.table`)
  - theme override (`themes/dark.css`)

Not developed:

- no versioned stylesheet path (for example `/styles/synthia-core.v1.css`)

## Token Contract

Implemented tokens from `shared/theme/tokens.css`:

- colors:
  - `--sx-bg`
  - `--sx-panel`
  - `--sx-border`
  - `--sx-text`
  - `--sx-text-muted`
  - `--sx-accent`
  - `--sx-success`
  - `--sx-warning`
  - `--sx-danger`
- spacing:
  - `--sx-space-1` .. `--sx-space-6`
- shape:
  - `--sx-radius-sm`
  - `--sx-radius-md`
  - `--sx-radius-lg`
- depth:
  - `--sx-shadow-1`
  - `--sx-shadow-2`
- typography:
  - `--sx-font-sans`

Backwards-compatible `--color-*`, `--radius-*`, `--shadow-*`, and `--font-sans` aliases remain available.

## Shared CSS Selectors

Code-verified selectors currently defined in Core theme styles:

From `shared/theme/components.css`:

- `.card`
- `.btn`
- `.btn-primary`
- `.pill`
- iframe injected utility selectors:
  - `.home-mini`
  - `.home-mini.warn`
  - `.home-mini.bad`
  - `.home-head`
  - `.home-status-card`
  - `.home-status-card.tone-ok`
  - `.home-status-card.tone-warn`
  - `.home-status-card.tone-danger`
  - `.home-panel`
  - `.home-panel-head`
  - `.home-panel h2`

From `shared/theme/base.css`:

- element selectors: `:root`, `body`, `h1`, `a`, `hr`
- theme mode selectors: `:root[data-theme="dark"]`, `:root[data-theme="light"]`

Contract boundary:

- Addons should treat `components.css` selectors as reusable theme primitives.
- Page-specific selectors under `frontend/src/core/pages/*.css` are not a stable addon contract.

## Addon-Safe Usage Rules

For UI rendered inside the Core app document (embedded React addon routes), addons can consume the token contract directly:

- prefer `hsl(var(--sx-...))` for colors
- prefer `var(--sx-radius-...)` and `var(--sx-shadow-...)`
- avoid hardcoded colors when token equivalents exist

For standalone addon UIs rendered in iframe (`/addons/:addonId` -> proxied addon app):

- CSS variables from Core do not cross iframe boundary automatically
- addons can load the shared stylesheet from frontend host endpoint: `/styles/synthia-core.css`
- Core still applies best-effort token/base-class injection only when iframe is same-origin accessible; direct cross-origin iframe targets remain isolated

See addon author usage details in [addon-ui-styling.md](./addon-ui-styling.md).
See full token reference in [ui-theme.md](./ui-theme.md).

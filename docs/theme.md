# Theme System Contract for Addons

Last Updated: 2026-03-08 15:33 US/Pacific

## Scope

This document describes the currently implemented Core theme token system in `frontend/src/theme/*`.

## Theme Loading

Implemented:

- Core imports `frontend/src/theme/index.css` from `frontend/src/main.tsx`.
- `index.css` loads:
  - `tokens.css` (base tokens)
  - `base.css` (global elements)
  - `components.css` (`.card`, `.btn`, `.btn-primary`, `.pill`)
  - theme overrides (`themes/dark.css`, `themes/light.css`)

Not developed:

- no dedicated exported standalone theme asset endpoint (for example `/static/synthia-theme.css`)

## Token Contract

Implemented tokens from `frontend/src/theme/tokens.css`:

- colors:
  - `--color-bg`
  - `--color-panel`
  - `--color-border`
  - `--color-text`
  - `--color-text-muted`
  - `--color-primary`
  - `--color-success`
  - `--color-warning`
  - `--color-danger`
- shape:
  - `--radius-sm`
  - `--radius-md`
  - `--radius-lg`
- depth:
  - `--shadow-sm`
  - `--shadow-md`
- typography:
  - `--font-sans`

## Addon-Safe Usage Rules

For UI rendered inside the Core app document (embedded React addon routes), addons can consume the token contract directly:

- prefer `hsl(var(--color-...))` for colors
- prefer `var(--radius-...)` and `var(--shadow-...)`
- avoid hardcoded colors when token equivalents exist

For standalone addon UIs rendered in iframe (`/addons/:addonId` -> proxied addon app):

- CSS variables from Core do not cross iframe boundary
- addon must provide its own stylesheet and design tokens
- Core applies best-effort token/base-class injection only when iframe is same-origin accessible; direct cross-origin iframe targets remain isolated

See addon author usage details in [addon-ui-styling.md](./addon-ui-styling.md).

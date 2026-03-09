# Addon UI Styling Guide

Last Updated: 2026-03-08 15:33 US/Pacific

## Purpose

Guide for addon authors who want visual compatibility with Synthia Core while preserving addon UI isolation.

## 1) Rendering Modes

### Embedded addon UI (same document as Core app)

When addon UI is loaded as part of Core frontend route tree, it can use Core theme tokens/classes directly because CSS is shared in the same DOM.

Available shared classes from `frontend/src/theme/components.css`:

- `.card`
- `.btn`
- `.btn-primary`
- `.pill`

Available shared tokens from `frontend/src/theme/tokens.css`:

- `--color-bg`, `--color-panel`, `--color-border`
- `--color-text`, `--color-text-muted`
- `--color-primary`, `--color-success`, `--color-warning`, `--color-danger`
- `--radius-sm`, `--radius-md`, `--radius-lg`
- `--shadow-sm`, `--shadow-md`
- `--font-sans`

### Standalone addon UI (iframe via `/addons/{addon_id}`)

Standalone addon UI is served from addon container and rendered inside an iframe. It does not inherit Core CSS variables or classes.

## 2) Compatibility Rules

- Do not rely on parent-window styles for standalone addon pages.
- Keep addon CSS scoped to addon-owned selectors.
- Avoid global resets that could conflict when embedding shared bundles.
- Keep fallback values for design tokens in addon CSS.

Example:

```css
.addon-root {
  color: hsl(var(--color-text, 210 40% 98%));
  background: hsl(var(--color-bg, 222 84% 5%));
  border-color: hsl(var(--color-border, 217 20% 20%));
}
```

## 3) Current Core-to-Standalone Styling Boundary

Implemented:

- Core provides iframe container and proxy pathing for standalone addon UI.
- Core performs best-effort theme token + base class CSS injection into iframe when iframe document is same-origin accessible (for proxied addon UI paths).
- Cross-origin direct host-port iframe targets cannot be injected by browser security policy.

Not developed:

- versioned addon styling SDK/package

Implemented shared stylesheet endpoint:

- Core frontend host now serves shared theme CSS at `/styles/synthia-core.css`.
- Example: if Core UI is on `http://10.0.0.100:8080`, addons can use `http://10.0.0.100:8080/styles/synthia-core.css`.

Standalone addon usage example:

```html
<link rel="stylesheet" href="http://10.0.0.100:8080/styles/synthia-core.css" />
```

## 4) Recommendation for Addon Authors

- For embedded mode: consume Core tokens/classes.
- For standalone mode: ship addon-owned CSS, optionally mirroring Core token names with local fallbacks.
- Treat Core token names as compatibility hints, not a strict semver-stable external SDK.

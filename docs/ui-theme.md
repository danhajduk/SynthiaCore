# Synthia UI Theme System

Synthia Core exposes an official shared UI theme contract in `shared/theme/`.

## Files

- `shared/theme/tokens.css`: canonical token variables (`--sx-*`)
- `shared/theme/base.css`: global base styles
- `shared/theme/components.css`: reusable primitives (`.card`, `.panel`, `.btn`, `.badge`, `.form-input`, `.table`)
- `shared/theme/themes/dark.css`: dark theme overrides
- `shared/theme/index.css`: aggregate import

Core imports `shared/theme/index.css` from frontend entry (`frontend/src/main.tsx`).

## Token Reference

### Colors

- `--sx-bg`
- `--sx-panel`
- `--sx-border`
- `--sx-text`
- `--sx-text-muted`
- `--sx-accent`
- `--sx-success`
- `--sx-warning`
- `--sx-danger`

### Spacing

- `--sx-space-1`
- `--sx-space-2`
- `--sx-space-3`
- `--sx-space-4`
- `--sx-space-5`
- `--sx-space-6`

### Radius

- `--sx-radius-sm`
- `--sx-radius-md`
- `--sx-radius-lg`

### Shadows

- `--sx-shadow-1`
- `--sx-shadow-2`

### Typography

- `--sx-font-sans`

## Addon Usage

For addon UIs rendered in the same DOM or same-origin iframe, use the shared tokens/classes directly.

Example:

```css
.my-addon-card {
  background: hsl(var(--sx-panel));
  color: hsl(var(--sx-text));
  border: 1px solid hsl(var(--sx-border));
  border-radius: var(--sx-radius-md);
  padding: var(--sx-space-4);
}

.my-addon-btn {
  background: hsl(var(--sx-accent));
  color: white;
  border-radius: var(--sx-radius-sm);
  padding: var(--sx-space-2) var(--sx-space-3);
}
```

For iframe addons, Core theme injection also includes `--sx-*` tokens and base primitive classes.

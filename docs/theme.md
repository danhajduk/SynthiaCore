# Theme System Contract for Addons

## CSS file location

`/static/synthia-theme.css`

## Usage for React apps

```ts
import "/static/synthia-theme.css";
```

## Usage for static addons

```html
<link rel="stylesheet" href="/static/synthia-theme.css">
```

## Tokens available

- `--color-bg`
- `--color-panel`
- `--color-border`
- `--color-text`
- `--color-text-muted`
- `--color-primary`
- `--color-success`
- `--color-warning`
- `--color-danger`
- `--radius-sm`
- `--radius-md`
- `--radius-lg`
- `--shadow-sm`
- `--shadow-md`
- `--font-sans`

## Rule

Do not hardcode colors in application CSS.
Use theme tokens instead.

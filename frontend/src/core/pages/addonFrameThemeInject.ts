const TOKEN_NAMES = [
  "--color-bg",
  "--color-panel",
  "--color-border",
  "--color-text",
  "--color-text-muted",
  "--color-primary",
  "--color-success",
  "--color-warning",
  "--color-danger",
  "--radius-sm",
  "--radius-md",
  "--radius-lg",
  "--shadow-sm",
  "--shadow-md",
  "--font-sans",
];

const STYLE_ID = "synthia-core-theme-inject";

const COMPONENT_RULES = `
body{font-family:var(--font-sans);background:hsl(var(--color-bg));color:hsl(var(--color-text));}
a{color:hsl(var(--color-primary));text-decoration:none;}
.card{background:hsl(var(--color-panel));border:1px solid hsl(var(--color-border));border-radius:var(--radius-md);padding:16px;}
.btn{border-radius:var(--radius-sm);border:none;padding:6px 12px;cursor:pointer;}
.btn-primary{background:hsl(var(--color-primary));color:white;}
.pill{border-radius:999px;padding:2px 8px;font-size:12px;}
`;

export function injectCoreCssIntoIframe(iframe: HTMLIFrameElement): boolean {
  try {
    const childDoc = iframe.contentDocument;
    if (!childDoc) return false;

    const childRoot = childDoc.documentElement;
    if (!childRoot) return false;
    const parentStyles = window.getComputedStyle(document.documentElement);
    for (const token of TOKEN_NAMES) {
      const value = parentStyles.getPropertyValue(token);
      if (value.trim()) {
        childRoot.style.setProperty(token, value.trim());
      }
    }

    let styleEl = childDoc.getElementById(STYLE_ID) as HTMLStyleElement | null;
    if (!styleEl) {
      styleEl = childDoc.createElement("style");
      styleEl.id = STYLE_ID;
      (childDoc.head || childDoc.documentElement).appendChild(styleEl);
    }
    styleEl.textContent = COMPONENT_RULES;
    return true;
  } catch {
    return false;
  }
}

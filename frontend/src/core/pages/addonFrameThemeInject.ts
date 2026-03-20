const TOKEN_NAMES = [
  "--sx-bg",
  "--sx-panel",
  "--sx-border",
  "--sx-text",
  "--sx-text-muted",
  "--sx-accent",
  "--sx-success",
  "--sx-warning",
  "--sx-danger",
  "--sx-space-1",
  "--sx-space-2",
  "--sx-space-3",
  "--sx-space-4",
  "--sx-space-5",
  "--sx-space-6",
  "--sx-radius-sm",
  "--sx-radius-md",
  "--sx-radius-lg",
  "--sx-shadow-1",
  "--sx-shadow-2",
  "--sx-font-sans",
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

const STYLE_ID = "hexe-core-theme-inject";
const STYLE_MARKER_ATTR = "data-hexe-core-theme";
const ROOT_MARKER_ATTR = "data-hexe-core-theme-injected";

const COMPONENT_RULES = `
body{font-family:var(--sx-font-sans,var(--font-sans));background:hsl(var(--sx-bg,var(--color-bg)));color:hsl(var(--sx-text,var(--color-text)));}
a{color:hsl(var(--sx-accent,var(--color-primary)));text-decoration:none;}
.card{background:hsl(var(--sx-panel,var(--color-panel)));border:1px solid hsl(var(--sx-border,var(--color-border)));border-radius:var(--sx-radius-md,var(--radius-md));padding:var(--sx-space-4,16px);}
.btn{border-radius:var(--sx-radius-sm,var(--radius-sm));border:none;padding:var(--sx-space-2,6px) var(--sx-space-3,12px);cursor:pointer;}
.btn-primary{background:hsl(var(--sx-accent,var(--color-primary)));color:white;}
.pill{border-radius:999px;padding:2px var(--sx-space-2,8px);font-size:12px;}
.home-mini{border:2px solid hsl(var(--sx-border,var(--color-border)));border-radius:var(--sx-radius-md,var(--radius-md));background:hsl(var(--sx-panel,var(--color-panel)));padding:10px;}
.home-mini.warn{border-color:hsl(var(--sx-warning,var(--color-warning)));}
.home-mini.bad{border-color:hsl(var(--sx-danger,var(--color-danger)));}
.home-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;}
.home-status-card{border:2px solid hsl(var(--sx-border,var(--color-border)));border-radius:var(--sx-radius-md,var(--radius-md));background:hsl(var(--sx-panel,var(--color-panel)));padding:14px;display:flex;justify-content:space-between;gap:14px;align-items:center;}
.home-status-card.tone-ok{border-color:hsl(var(--sx-success,var(--color-success)));}
.home-status-card.tone-warn{border-color:hsl(var(--sx-warning,var(--color-warning)));}
.home-status-card.tone-danger{border-color:hsl(var(--sx-danger,var(--color-danger)));}
.home-panel{border:1px solid hsl(var(--sx-border,var(--color-border)));border-radius:var(--sx-radius-md,var(--radius-md));background:hsl(var(--sx-panel,var(--color-panel)));padding:12px;min-height:250px;}
.home-panel h2{margin:0;font-size:16px;}
.home-panel-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;}
`;

export type IframeThemeInjectResult = {
  injected: boolean;
  reason: "ok" | "no_document" | "no_root" | "cross_origin" | "error";
};

export function injectCoreCssIntoIframe(iframe: HTMLIFrameElement): IframeThemeInjectResult {
  try {
    const childWindow = iframe.contentWindow;
    if (!childWindow) return { injected: false, reason: "no_document" };
    if (childWindow.location.origin !== window.location.origin) {
      return { injected: false, reason: "cross_origin" };
    }
    const childDoc = iframe.contentDocument;
    if (!childDoc) return { injected: false, reason: "no_document" };

    const childRoot = childDoc.documentElement;
    if (!childRoot) return { injected: false, reason: "no_root" };
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
    styleEl.setAttribute(STYLE_MARKER_ATTR, "true");
    styleEl.textContent = typeof COMPONENT_RULES === "string" ? COMPONENT_RULES : "";
    childRoot.setAttribute(ROOT_MARKER_ATTR, "true");
    return { injected: true, reason: "ok" };
  } catch {
    return { injected: false, reason: "error" };
  }
}

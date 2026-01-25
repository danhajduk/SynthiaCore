import type { FrontendAddonModule, AddonNavItem } from "../../types/addon";
import type { RouteObject } from "react-router-dom";

function isAddonModule(x: any): x is FrontendAddonModule {
  return (
    x &&
    typeof x === "object" &&
    x.meta &&
    typeof x.meta.id === "string" &&
    typeof x.meta.name === "string" &&
    typeof x.meta.basePath === "string" &&
    Array.isArray(x.routes) &&
    x.navItem &&
    typeof x.navItem.label === "string" &&
    typeof x.navItem.path === "string"
  );
}

/**
 * Vite glob import loads *synced* addon frontends from src/addons/<addon-name>/index.ts
 * If an addon doesn't exist or has invalid exports, it's skipped.
 */
const modules = import.meta.glob("../../addons/*/index.ts", { eager: true });

export function loadAddons(): FrontendAddonModule[] {
  const out: FrontendAddonModule[] = [];

  for (const [path, mod] of Object.entries(modules)) {
    const candidate = (mod as any) as Partial<FrontendAddonModule>;

    if (!isAddonModule(candidate)) {
      // eslint-disable-next-line no-console
      console.warn("[addons] Skipping invalid addon module:", path, mod);
      continue;
    }
    out.push(candidate);
  }

  // stable order
  out.sort((a, b) => a.meta.id.localeCompare(b.meta.id));
  return out;
}

export function getAddonRoutes(): RouteObject[] {
  return loadAddons().flatMap((a) => a.routes);
}

export function getNavItems(): AddonNavItem[] {
  return loadAddons().map((a) => a.navItem);
}

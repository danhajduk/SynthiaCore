import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { API_BASE } from "./api/client";

export const DEFAULT_PLATFORM_NAME = "Hexe AI";
export const DEFAULT_PLATFORM_SHORT = "Hexe";
export const DEFAULT_PLATFORM_DOMAIN = "hexe-ai.com";
export const DEFAULT_PLATFORM_CORE_NAME = "Hexe Core";
export const DEFAULT_PLATFORM_SUPERVISOR_NAME = "Hexe Supervisor";
export const DEFAULT_PLATFORM_NODES_NAME = "Hexe Nodes";
export const DEFAULT_PLATFORM_ADDONS_NAME = "Hexe Addons";
export const DEFAULT_PLATFORM_DOCS_NAME = "Hexe Docs";
export const DEFAULT_LEGACY_INTERNAL_NAMESPACE = "synthia";
export const DEFAULT_LEGACY_COMPATIBILITY_NOTE =
  "Some stable technical identifiers still use `synthia` where changing them would break compatibility.";

export type PlatformBranding = {
  platformName: string;
  platformShort: string;
  platformDomain: string;
  coreName: string;
  supervisorName: string;
  nodesName: string;
  addonsName: string;
  docsName: string;
  legacyInternalNamespace: string;
  legacyCompatibilityNote: string;
};

export const DEFAULT_BRANDING: PlatformBranding = {
  platformName: DEFAULT_PLATFORM_NAME,
  platformShort: DEFAULT_PLATFORM_SHORT,
  platformDomain: DEFAULT_PLATFORM_DOMAIN,
  coreName: DEFAULT_PLATFORM_CORE_NAME,
  supervisorName: DEFAULT_PLATFORM_SUPERVISOR_NAME,
  nodesName: DEFAULT_PLATFORM_NODES_NAME,
  addonsName: DEFAULT_PLATFORM_ADDONS_NAME,
  docsName: DEFAULT_PLATFORM_DOCS_NAME,
  legacyInternalNamespace: DEFAULT_LEGACY_INTERNAL_NAMESPACE,
  legacyCompatibilityNote: DEFAULT_LEGACY_COMPATIBILITY_NOTE,
};

type PlatformPayload = Record<string, unknown>;

const PlatformBrandingContext = createContext<PlatformBranding>(DEFAULT_BRANDING);

function readText(value: unknown, fallback: string): string {
  const text = String(value || "").trim();
  return text || fallback;
}

export function resolvePlatformBranding(payload?: PlatformPayload | null, fallback: PlatformBranding = DEFAULT_BRANDING): PlatformBranding {
  const data = payload && typeof payload === "object" ? payload : {};
  return {
    platformName: readText(data.platform_name, fallback.platformName),
    platformShort: readText(data.platform_short, fallback.platformShort),
    platformDomain: readText(data.platform_domain, fallback.platformDomain),
    coreName: readText(data.core_name, fallback.coreName),
    supervisorName: readText(data.supervisor_name, fallback.supervisorName),
    nodesName: readText(data.nodes_name, fallback.nodesName),
    addonsName: readText(data.addons_name, fallback.addonsName),
    docsName: readText(data.docs_name, fallback.docsName),
    legacyInternalNamespace: readText(data.legacy_internal_namespace, fallback.legacyInternalNamespace),
    legacyCompatibilityNote: readText(data.legacy_compatibility_note, fallback.legacyCompatibilityNote),
  };
}

export function usePlatformBranding(): PlatformBranding {
  return useContext(PlatformBrandingContext);
}

export function usePlatformLabel(component: "platform" | "core" | "supervisor" | "nodes" | "addons" | "docs"): string {
  const branding = usePlatformBranding();
  switch (component) {
    case "core":
      return branding.coreName;
    case "supervisor":
      return branding.supervisorName;
    case "nodes":
      return branding.nodesName;
    case "addons":
      return branding.addonsName;
    case "docs":
      return branding.docsName;
    default:
      return branding.platformName;
  }
}

export function useLegacyCompatibilityNote(): string {
  return usePlatformBranding().legacyCompatibilityNote;
}

export function PlatformBrandingProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState<PlatformBranding>(DEFAULT_BRANDING);

  useEffect(() => {
    let cancelled = false;

    async function loadBranding() {
      try {
        const res = await fetch(`${API_BASE}/api/system/platform`, {
          cache: "no-store",
          credentials: "same-origin",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const payload = (await res.json()) as PlatformPayload;
        if (cancelled) return;
        setBranding(resolvePlatformBranding(payload));
      } catch {
        if (!cancelled) {
          setBranding(DEFAULT_BRANDING);
        }
      }
    }

    void loadBranding();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    document.title = branding.coreName;
  }, [branding.coreName]);

  return <PlatformBrandingContext.Provider value={branding}>{children}</PlatformBrandingContext.Provider>;
}

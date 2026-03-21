import { describe, expect, it } from "vitest";

import {
  DEFAULT_BRANDING,
  DEFAULT_PLATFORM_ADDONS_NAME,
  DEFAULT_PLATFORM_DOCS_NAME,
  DEFAULT_PLATFORM_NODES_NAME,
  DEFAULT_PLATFORM_SUPERVISOR_NAME,
  resolvePlatformBranding,
} from "./branding";

describe("platform branding resolution", () => {
  it("returns full defaults when payload is missing", () => {
    expect(resolvePlatformBranding(undefined)).toEqual(DEFAULT_BRANDING);
  });

  it("resolves expanded component labels from the platform endpoint payload", () => {
    const branding = resolvePlatformBranding({
      core_id: "0123456789abcdef",
      platform_name: "Acme AI",
      platform_short: "Acme",
      platform_domain: "acme.example",
      core_name: "Acme Core",
      supervisor_name: "Acme Supervisor",
      nodes_name: "Acme Nodes",
      addons_name: "Acme Addons",
      docs_name: "Acme Docs",
      legacy_internal_namespace: "legacy",
      legacy_compatibility_note: "Legacy namespace remains active internally.",
    });

    expect(branding.coreId).toBe("0123456789abcdef");
    expect(branding.platformName).toBe("Acme AI");
    expect(branding.coreName).toBe("Acme Core");
    expect(branding.supervisorName).toBe("Acme Supervisor");
    expect(branding.nodesName).toBe("Acme Nodes");
    expect(branding.addonsName).toBe("Acme Addons");
    expect(branding.docsName).toBe("Acme Docs");
    expect(branding.legacyInternalNamespace).toBe("legacy");
  });

  it("keeps component-label fallbacks stable when only partial data is returned", () => {
    const branding = resolvePlatformBranding({
      platform_name: "Hexe AI",
      core_name: "Hexe Core",
    });

    expect(branding.supervisorName).toBe(DEFAULT_PLATFORM_SUPERVISOR_NAME);
    expect(branding.nodesName).toBe(DEFAULT_PLATFORM_NODES_NAME);
    expect(branding.addonsName).toBe(DEFAULT_PLATFORM_ADDONS_NAME);
    expect(branding.docsName).toBe(DEFAULT_PLATFORM_DOCS_NAME);
  });
});

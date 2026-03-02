import { describe, expect, it } from "vitest";

import { installActionItems, parseInstallFailure } from "./addonStoreErrorUtils";

describe("parseInstallFailure", () => {
  it("extracts detail error code from JSON payload", () => {
    const payload = JSON.stringify({
      detail: {
        error: "catalog_profile_layout_mismatch",
        remediation_path: "embedded_repackage",
        layout_hint: "service_layout_app_main",
      },
    });
    const parsed = parseInstallFailure(409, payload);
    expect(parsed.message).toBe("install_http_409: catalog_profile_layout_mismatch");
    expect(parsed.detail?.remediation_path).toBe("embedded_repackage");
    expect(parsed.detail?.layout_hint).toBe("service_layout_app_main");
  });

  it("falls back to raw payload when JSON detail is unavailable", () => {
    const parsed = parseInstallFailure(400, "install_failed");
    expect(parsed.message).toBe("install_http_400: install_failed");
    expect(parsed.detail).toBeNull();
  });
});

describe("installActionItems", () => {
  it("returns embedded remediation actions", () => {
    const actions = installActionItems({ remediation_path: "embedded_repackage" });
    expect(actions).toHaveLength(2);
    expect(actions[0]).toContain("embedded layout");
  });

  it("returns standalone remediation actions", () => {
    const actions = installActionItems({ remediation_path: "standalone_deploy_register" });
    expect(actions).toHaveLength(2);
    expect(actions[0]).toContain("externally");
  });
});

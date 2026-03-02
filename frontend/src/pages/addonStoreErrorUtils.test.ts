import { describe, expect, it } from "vitest";

import { installActionItems, installModeForPackageProfile, parseInstallFailure } from "./addonStoreErrorUtils";

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

  it("handles non-string detail error fields without throwing", () => {
    const payload = JSON.stringify({
      detail: {
        error: { nested: "not-a-string" },
        code: 404,
      },
    });
    const parsed = parseInstallFailure(400, payload);
    expect(parsed.message).toBe("install_http_400: install_failed");
    expect(parsed.detail?.error).toBeUndefined();
    expect(parsed.detail?.code).toBeUndefined();
    expect(parsed.detail?.remediation_path).toBeUndefined();
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
    expect(actions).toHaveLength(3);
    expect(actions[0]).toContain("externally");
    expect(actions[2]).toContain("catalog_package_profile_unsupported.md");
  });

  it("returns standalone install-mode remediation actions", () => {
    const actions = installActionItems({ remediation_path: "standalone_service_install" });
    expect(actions).toHaveLength(3);
    expect(actions[0]).toContain("install_mode=standalone_service");
  });
});

describe("installModeForPackageProfile", () => {
  it("maps standalone profiles to standalone_service mode", () => {
    expect(installModeForPackageProfile("standalone_service")).toBe("standalone_service");
    expect(installModeForPackageProfile("standalone-service")).toBe("standalone_service");
  });

  it("defaults unknown or embedded profiles to embedded_addon mode", () => {
    expect(installModeForPackageProfile("embedded_addon")).toBe("embedded_addon");
    expect(installModeForPackageProfile("random_profile")).toBe("embedded_addon");
    expect(installModeForPackageProfile(undefined)).toBe("embedded_addon");
  });
});

export type InstallErrorDetail = {
  error?: string;
  code?: string;
  hint?: string;
  remediation_path?: string;
  requested_install_mode?: string;
  source_id?: string;
  artifact_url?: string;
  layout_hint?: string;
  catalog_release_package_profile?: string;
  catalog_release_version?: string;
};

export type InstallErrorParseResult = {
  message: string;
  detail: InstallErrorDetail | null;
};

function parseJson(value: string): unknown | null {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function firstNonEmptyString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value !== "string") continue;
    const trimmed = value.trim();
    if (trimmed) return trimmed;
  }
  return null;
}

function optionalString(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function asObject(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object") return null;
  return value as Record<string, unknown>;
}

function normalizeDetail(
  detail: Record<string, unknown>,
  nestedDetails: Record<string, unknown> | null,
  resolvedCode: string | null,
): InstallErrorDetail {
  return {
    error: optionalString(detail.error),
    code: optionalString(detail.code) || resolvedCode || undefined,
    hint: optionalString(detail.hint) || optionalString(nestedDetails?.hint),
    remediation_path:
      optionalString(detail.remediation_path) || optionalString(nestedDetails?.remediation_path),
    requested_install_mode:
      optionalString(detail.requested_install_mode) || optionalString(nestedDetails?.requested_install_mode),
    source_id: optionalString(detail.source_id) || optionalString(nestedDetails?.source_id),
    artifact_url: optionalString(detail.artifact_url) || optionalString(nestedDetails?.artifact_url),
    layout_hint: optionalString(detail.layout_hint) || optionalString(nestedDetails?.layout_hint),
    catalog_release_package_profile:
      optionalString(detail.catalog_release_package_profile) ||
      optionalString(nestedDetails?.catalog_release_package_profile),
    catalog_release_version:
      optionalString(detail.catalog_release_version) ||
      optionalString(nestedDetails?.catalog_release_version),
  };
}

export function parseInstallFailure(status: number, payloadText: string): InstallErrorParseResult {
  const parsed = parseJson(payloadText);
  if (parsed && typeof parsed === "object") {
    const asObj = parsed as Record<string, unknown>;
    const detail = asObj.detail;
    if (detail && typeof detail === "object") {
      const detailObj = detail as Record<string, unknown>;
      const nestedError = asObject(detailObj.error);
      const nestedDetails = asObject(nestedError?.details);
      const resolvedCode =
        firstNonEmptyString(
          detailObj.error,
          detailObj.code,
          nestedError?.code,
          nestedError?.error,
          "install_failed",
        ) || "install_failed";
      const typed = normalizeDetail(detailObj, nestedDetails, resolvedCode);
      return {
        message: `install_http_${status}: ${resolvedCode}`,
        detail: typed,
      };
    }
  }
  return {
    message: `install_http_${status}: ${payloadText}`,
    detail: null,
  };
}

export function installActionItems(detail: InstallErrorDetail | null): string[] {
  if (!detail) return [];
  if (detail.remediation_path === "embedded_repackage") {
    return [
      "Rebuild and publish artifact with embedded layout (backend/addon.py).",
      "Keep release package_profile=embedded_addon and refresh source before retry.",
    ];
  }
  if (detail.remediation_path === "standalone_deploy_register") {
    return [
      "Deploy the service artifact externally (container/systemd/host process).",
      "Register the service via /api/admin/addons/registry and validate health/proxy.",
      "See docs/distributed_addons/catalog_package_profile_unsupported.md for triage and remediation details.",
    ];
  }
  if (detail.remediation_path === "standalone_service_install") {
    return [
      "Retry install from Addon Store; request now sends install_mode=standalone_service automatically.",
      "If retry still fails, refresh source and verify release package_profile is standalone_service.",
      "See docs/distributed_addons/catalog_package_profile_unsupported.md for mode-selection diagnostics.",
    ];
  }
  return [];
}

export function installModeForPackageProfile(profile: string | null | undefined): "embedded_addon" | "standalone_service" {
  const normalized = String(profile || "embedded_addon")
    .trim()
    .toLowerCase()
    .replace(/[-\s]+/g, "_");
  if (normalized === "standalone_service" || normalized === "standalone") {
    return "standalone_service";
  }
  return "embedded_addon";
}

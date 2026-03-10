import { addonUiFrameSrc } from "./addonFrameUrl";

export type AddonUiStatusPayload = {
  loaded?: boolean | null;
  runtime_state?: string | null;
  ui_reachable?: boolean | null;
  ui_reason?: string | null;
  ui_embed_target?: string | null;
  standalone_runtime?: {
    published_ports?: unknown;
  } | null;
};

type AddonUiEmbedState = {
  frameSrc: string;
  reachable: boolean;
  reason: string;
};

export function resolveAddonUiEmbedState(
  addonId: string,
  payload: AddonUiStatusPayload | null | undefined,
): AddonUiEmbedState {
  const fallbackSrc = addonUiFrameSrc(addonId);
  if (!payload) {
    return { frameSrc: fallbackSrc, reachable: false, reason: "status_unavailable" };
  }

  const runtimeState = String(payload.runtime_state || "").trim().toLowerCase();
  const rawTarget = typeof payload.ui_embed_target === "string" ? payload.ui_embed_target.trim() : "";
  const publishedPortsRaw = payload.standalone_runtime?.published_ports;
  const publishedPorts = Array.isArray(publishedPortsRaw)
    ? publishedPortsRaw.map((item) => String(item || "").trim())
    : [];
  const directUrl = directUiUrlFromPublishedPorts(publishedPorts);
  let frameSrc = fallbackSrc;
  if (payload.loaded !== true && runtimeState === "running" && directUrl) {
    frameSrc = directUrl;
  } else if (rawTarget) {
    try {
      frameSrc = new URL(rawTarget, fallbackSrc).toString();
    } catch {
      frameSrc = fallbackSrc;
    }
  }
  const reachable = payload.ui_reachable === true;
  const embeddedLocal =
    payload.loaded === true &&
    !payload.standalone_runtime &&
    (runtimeState === "" || runtimeState === "unknown");
  const reason =
    typeof payload.ui_reason === "string" && payload.ui_reason.trim() ? payload.ui_reason.trim() : "unknown";
  if (!reachable && embeddedLocal) {
    return { frameSrc, reachable: true, reason: "embedded_local" };
  }
  return { frameSrc, reachable, reason };
}

export function addonUiFallbackReason(reason: string): string {
  switch (reason) {
    case "runtime_unavailable":
      return "Runtime status is not available yet.";
    case "runtime_not_running":
      return "Addon runtime is not running yet.";
    case "no_published_ports":
      return "Addon runtime has no published UI ports.";
    case "health_unhealthy":
      return "Addon runtime is unhealthy.";
    case "status_error":
      return "Unable to query addon runtime status.";
    case "status_unavailable":
      return "No addon runtime status was returned.";
    case "embedded_local":
      return "Embedded addon UI is served by Core.";
    case "frame_load_failed":
      return "The addon UI failed to load in the frame.";
    case "timeout":
      return "Timed out waiting for addon UI readiness.";
    default:
      return "Addon UI is not reachable yet.";
  }
}

function directUiUrlFromPublishedPorts(publishedPorts: string[]): string | null {
  const published = publishedPorts.find((entry) => entry.includes("->"));
  if (!published) return null;
  const left = published.split("->", 1)[0].trim();
  const idx = left.lastIndexOf(":");
  if (idx <= 0 || idx >= left.length - 1) return null;

  const rawHost = left.slice(0, idx).trim();
  const port = left.slice(idx + 1).trim();
  if (!/^\d+$/.test(port)) return null;

  const browserHost = typeof window !== "undefined" ? window.location.hostname : "127.0.0.1";
  const browserProtocol =
    typeof window !== "undefined" && window.location.protocol === "https:" ? "https:" : "http:";
  const host =
    !rawHost || rawHost === "0.0.0.0" || rawHost === "::" || rawHost === "[::]" || rawHost === "127.0.0.1"
      ? browserHost
      : rawHost;
  return `${browserProtocol}//${host}:${port}`;
}

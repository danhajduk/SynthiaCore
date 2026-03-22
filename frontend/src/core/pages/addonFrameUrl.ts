import { API_BASE } from "../api/client";
import { addonUiProxyPath } from "../router/proxyRoutes";

function defaultBackendBase(locationLike?: Pick<Location, "origin" | "hostname" | "protocol" | "port">): string {
  const activeLocation =
    locationLike ||
    (typeof window !== "undefined"
      ? window.location
      : undefined);
  if (!activeLocation) {
    return "http://127.0.0.1:9001";
  }
  const port = String(activeLocation.port || "").trim();
  if (!port || port === "80" || port === "443" || port === "9001") {
    return String(activeLocation.origin || "").replace(/\/+$/, "") || "http://127.0.0.1:9001";
  }
  const host = activeLocation.hostname || "127.0.0.1";
  const protocol = activeLocation.protocol === "https:" ? "https:" : "http:";
  return `${protocol}//${host}:9001`;
}

export function addonUiFrameSrc(
  addonId: string,
  backendBase?: string,
  locationLike?: Pick<Location, "origin" | "hostname" | "protocol" | "port">,
): string {
  const trimmed = String(addonId || "").trim();
  if (!trimmed) return "";
  const base = String(backendBase || API_BASE || defaultBackendBase(locationLike)).trim().replace(/\/+$/, "");
  const path = addonUiProxyPath(trimmed);
  return `${base}${path}`;
}

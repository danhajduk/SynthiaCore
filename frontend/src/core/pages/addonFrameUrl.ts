import { API_BASE } from "../api/client";

function defaultBackendBase(): string {
  if (typeof window === "undefined") {
    return "http://127.0.0.1:9001";
  }
  const host = window.location.hostname || "127.0.0.1";
  const protocol = window.location.protocol === "https:" ? "https:" : "http:";
  return `${protocol}//${host}:9001`;
}

export function addonUiFrameSrc(addonId: string, backendBase?: string): string {
  const trimmed = String(addonId || "").trim();
  if (!trimmed) return "";
  const base = String(backendBase || API_BASE || defaultBackendBase()).trim().replace(/\/+$/, "");
  const path = `/ui/addons/${encodeURIComponent(trimmed)}`;
  return `${base}${path}`;
}

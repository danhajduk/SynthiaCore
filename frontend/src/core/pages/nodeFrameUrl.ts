import { API_BASE } from "../api/client";

function defaultBackendBase(): string {
  if (typeof window === "undefined") {
    return "http://127.0.0.1:9001";
  }
  const host = window.location.hostname || "127.0.0.1";
  const protocol = window.location.protocol === "https:" ? "https:" : "http:";
  return `${protocol}//${host}:9001`;
}

export function nodeUiFrameSrc(nodeId: string, rawEndpoint?: string | null, rawHost?: string | null): string {
  const safeNodeId = String(nodeId || "").trim();
  if (!safeNodeId) return "";
  const base = String(API_BASE || defaultBackendBase()).trim().replace(/\/+$/, "");
  const endpoint = String(rawEndpoint || "").trim();
  if (endpoint) {
    return /^https?:\/\//i.test(endpoint) ? `${base}/ui/nodes/${encodeURIComponent(safeNodeId)}` : "";
  }
  const host = String(rawHost || "").trim();
  if (!host) return "";
  return `${base}/ui/nodes/${encodeURIComponent(safeNodeId)}`;
}

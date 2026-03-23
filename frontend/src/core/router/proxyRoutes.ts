export function addonUiProxyPath(addonId: string, path?: string): string {
  const safeAddonId = encodeURIComponent(String(addonId || "").trim());
  if (!safeAddonId) return "";
  const cleanPath = String(path || "").trim().replace(/^\/+/, "");
  return cleanPath ? `/addons/proxy/${safeAddonId}/${cleanPath}` : `/addons/proxy/${safeAddonId}/`;
}

export function nodeUiProxyPath(nodeId: string, path?: string): string {
  const safeNodeId = encodeURIComponent(String(nodeId || "").trim());
  if (!safeNodeId) return "";
  const cleanPath = String(path || "").trim().replace(/^\/+/, "");
  return cleanPath ? `/nodes/proxy/${safeNodeId}/${cleanPath}` : `/nodes/proxy/${safeNodeId}/`;
}

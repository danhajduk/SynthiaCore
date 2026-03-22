export function nodeUiFrameSrc(rawEndpoint?: string | null, rawHost?: string | null): string {
  const endpoint = String(rawEndpoint || "").trim();
  if (endpoint) {
    if (/^https?:\/\//i.test(endpoint)) {
      return endpoint.replace(/\/+$/, "");
    }
    return "";
  }
  const host = String(rawHost || "").trim();
  if (!host) return "";
  if (/^https?:\/\//i.test(host)) {
    return host.replace(/\/+$/, "");
  }
  const protocol =
    typeof window !== "undefined" && window.location.protocol === "https:" ? "https:" : "http:";
  return `${protocol}//${host.replace(/\/+$/, "")}`;
}

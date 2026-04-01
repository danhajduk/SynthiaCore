export function sanitizeNextPath(value?: string | null): string {
  const raw = String(value || "").trim();
  if (!raw.startsWith("/")) return "/";
  if (raw.startsWith("//")) return "/";
  if (/^\/[\\/]/.test(raw)) return "/";
  return raw;
}

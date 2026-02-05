const envBase = (import.meta as any).env?.VITE_API_BASE as string | undefined;
export const API_BASE = envBase && envBase.length > 0 ? envBase : "";

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GET ${path} failed: ${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

type AddonInfo = {
  id: string;
  name: string;
  version: string;
  description: string;
  show_sidebar?: boolean;
  enabled?: boolean;
};

export default function Addons() {
  const [addons, setAddons] = useState<AddonInfo[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    apiGet<AddonInfo[]>("/api/addons")
      .then(setAddons)
      .catch((e) => setErr(String(e)));
  }, []);

  async function setEnabled(addonId: string, enabled: boolean) {
    setErr(null);
    setBusy(addonId);
    try {
      const res = await fetch(`/api/addons/${addonId}/enable`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setAddons((prev) =>
        prev.map((a) => (a.id === addonId ? { ...a, enabled: data.enabled } : a))
      );
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>Addons</h1>
      {err && <pre style={{ whiteSpace: "pre-wrap" }}>{err}</pre>}
      {!err && (
        <div style={{ display: "grid", gap: 10 }}>
          {addons.length === 0 ? (
            <div style={{ opacity: 0.8 }}>No backend addons loaded.</div>
          ) : (
            addons.map((a) => (
              <div
                key={a.id}
                style={{
                  padding: 12,
                  borderRadius: 14,
                  border: "1px solid rgba(255,255,255,0.1)",
                  background: "rgba(255,255,255,0.04)",
                  display: "grid",
                  gap: 8,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{ fontWeight: 800 }}>{a.name}</div>
                  <div style={{ fontSize: 12, opacity: 0.7 }}>
                    {a.enabled === false ? "disabled" : "enabled"}
                  </div>
                </div>
                <div style={{ fontSize: 12, opacity: 0.7 }}>{a.id} • {a.version}</div>
                {a.description && <div style={{ marginTop: 6, opacity: 0.85 }}>{a.description}</div>}
                <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                  <button
                    onClick={() => setEnabled(a.id, !(a.enabled ?? true))}
                    disabled={busy === a.id}
                    style={{
                      padding: "6px 10px",
                      borderRadius: 8,
                      border: "1px solid rgba(255,255,255,0.15)",
                      background: "rgba(255,255,255,0.06)",
                      color: "white",
                      cursor: busy === a.id ? "not-allowed" : "pointer",
                      opacity: busy === a.id ? 0.6 : 1,
                    }}
                  >
                    {a.enabled === false ? "Enable" : "Disable"}
                  </button>
                  <a
                    href={`/addons/${a.id}`}
                    style={{
                      padding: "6px 10px",
                      borderRadius: 8,
                      border: "1px solid rgba(255,255,255,0.15)",
                      background: "rgba(255,255,255,0.06)",
                      color: "white",
                      textDecoration: "none",
                    }}
                  >
                    Open
                  </a>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

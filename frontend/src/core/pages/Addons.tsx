import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

type AddonMeta = { id: string; name: string; version: string; description: string };

export default function Addons() {
  const [addons, setAddons] = useState<AddonMeta[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    apiGet<AddonMeta[]>("/api/addons")
      .then(setAddons)
      .catch((e) => setErr(String(e)));
  }, []);

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
                }}
              >
                <div style={{ fontWeight: 800 }}>{a.name}</div>
                <div style={{ fontSize: 12, opacity: 0.7 }}>{a.id} • {a.version}</div>
                {a.description && <div style={{ marginTop: 6, opacity: 0.85 }}>{a.description}</div>}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

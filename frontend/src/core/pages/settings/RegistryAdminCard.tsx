import { useEffect, useState } from "react";
import "./admin-reload-card.css";
import { LS_API_BASE_KEY, defaultApiBase } from "./localKeys";

type RegisteredAddon = {
  id: string;
  name: string;
  version: string;
  base_url: string;
  capabilities: string[];
  health_status: string;
  last_seen?: string | null;
  auth_mode: string;
  tls_warning?: string | null;
};

export default function RegistryAdminCard() {
  const [apiBase, setApiBase] = useState<string>(() => localStorage.getItem(LS_API_BASE_KEY) || defaultApiBase());
  const [items, setItems] = useState<RegisteredAddon[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [version, setVersion] = useState("0.1.0");
  const [baseUrl, setBaseUrl] = useState("http://localhost:9002");
  const [capabilities, setCapabilities] = useState("");
  const [authMode, setAuthMode] = useState("none");

  useEffect(() => {
    localStorage.setItem(LS_API_BASE_KEY, apiBase);
  }, [apiBase]);

  const jsonHeaders: Record<string, string> = { "Content-Type": "application/json" };

  async function loadRegistry() {
    setErr(null);
    try {
      const res = await fetch(`${apiBase}/api/admin/addons/registry`, { credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = (await res.json()) as RegisteredAddon[];
      setItems(payload);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
      setItems([]);
    }
  }

  async function createOrUpdate() {
    setErr(null);
    setBusy(true);
    try {
      const body = {
        id,
        name: name || id,
        version,
        base_url: baseUrl,
        capabilities: capabilities
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
        auth_mode: authMode || "none",
      };
      const res = await fetch(`${apiBase}/api/admin/addons/registry`, {
        method: "POST",
        headers: jsonHeaders,
        credentials: "include",
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status} ${txt}`);
      }
      await loadRegistry();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setErr(null);
    try {
      const res = await fetch(`${apiBase}/api/admin/addons/registry/${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: jsonHeaders,
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await loadRegistry();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    }
  }

  useEffect(() => {
    loadRegistry();
  }, []);

  return (
    <section className="admin-card">
      <div className="admin-header">
        <div>
          <div className="admin-title">Addon Registry</div>
          <div className="admin-subtitle">Manage registered addon endpoints and capability metadata.</div>
        </div>
      </div>

      <div className="admin-form">
        <label className="admin-label">
          <div className="admin-label-text">Core API endpoint</div>
          <input value={apiBase} onChange={(e) => setApiBase(e.target.value)} className="admin-input" />
          <div className="admin-help">Target control-plane endpoint for registry operations.</div>
        </label>
        <div className="admin-log-label">Registry Controls</div>
        <div className="admin-actions">
          <button className="admin-btn" onClick={loadRegistry}>
            Refresh registry
          </button>
        </div>

        <label className="admin-label">
          <div className="admin-label-text">Addon ID</div>
          <input value={id} onChange={(e) => setId(e.target.value)} className="admin-input admin-input-mono" />
        </label>
        <label className="admin-label">
          <div className="admin-label-text">Name</div>
          <input value={name} onChange={(e) => setName(e.target.value)} className="admin-input" />
        </label>
        <label className="admin-label">
          <div className="admin-label-text">Version</div>
          <input value={version} onChange={(e) => setVersion(e.target.value)} className="admin-input" />
        </label>
        <label className="admin-label">
          <div className="admin-label-text">Addon base URL</div>
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} className="admin-input" />
        </label>
        <label className="admin-label">
          <div className="admin-label-text">Capabilities (comma-separated)</div>
          <input value={capabilities} onChange={(e) => setCapabilities(e.target.value)} className="admin-input" />
        </label>
        <label className="admin-label">
          <div className="admin-label-text">Auth Mode</div>
          <input value={authMode} onChange={(e) => setAuthMode(e.target.value)} className="admin-input" />
        </label>

        <div className="admin-actions">
          <button className="admin-btn admin-btn-primary" onClick={createOrUpdate} disabled={!id.trim() || busy}>
            {busy ? "Saving..." : "Create / Update"}
          </button>
        </div>

        {err && <pre className="admin-error">{err}</pre>}

        <div>
          <div className="admin-log-label">Registered Addons</div>
          <div className="admin-form">
            {items.map((x) => (
              <div key={x.id} className="admin-log">
                <div><strong>{x.id}</strong> • {x.name} • {x.version}</div>
                <div>base_url: {x.base_url}</div>
                <div>health: {x.health_status} • auth: {x.auth_mode} • last_seen: {x.last_seen ? new Date(x.last_seen).toLocaleString() : "-"}</div>
                <div>capabilities: {(x.capabilities || []).join(", ") || "-"}</div>
                {x.tls_warning && <div className="admin-error">{x.tls_warning}</div>}
                <div className="admin-actions">
                  <button className="admin-btn admin-btn-muted" onClick={() => remove(x.id)}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
            {items.length === 0 && <div className="admin-log">No registered addons yet. Add one to start managed registry operations.</div>}
          </div>
        </div>
      </div>
    </section>
  );
}

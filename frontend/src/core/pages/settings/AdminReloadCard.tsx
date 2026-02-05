import { useEffect, useMemo, useRef, useState } from "react";
import "./admin-reload-card.css";

type ReloadStartResponse = { started: boolean; unit?: string; log?: string };
type ReloadStatusResponse = { exists: boolean; tail: string };

const LS_TOKEN_KEY = "synthia_admin_token";
const LS_API_BASE_KEY = "synthia_api_base";

// Default to same host, backend port 9001
function defaultApiBase(): string {
  const host = window.location.hostname || "localhost";
  return `http://${host}:9001`;
}

export default function AdminReloadCard() {
  const [apiBase, setApiBase] = useState<string>(() => localStorage.getItem(LS_API_BASE_KEY) || defaultApiBase());
  const [token, setToken] = useState<string>(() => localStorage.getItem(LS_TOKEN_KEY) || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [tail, setTail] = useState<string>("");

  const pollTimer = useRef<number | null>(null);

  useEffect(() => {
    localStorage.setItem(LS_TOKEN_KEY, token);
  }, [token]);

  useEffect(() => {
    localStorage.setItem(LS_API_BASE_KEY, apiBase);
  }, [apiBase]);

  const headers = useMemo(() => {
    const h: Record<string, string> = {};
    if (token.trim()) h["X-Admin-Token"] = token.trim();
    return h;
  }, [token]);

  function stopPolling() {
    if (pollTimer.current) {
      window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }

  async function fetchStatusOnce() {
    const res = await fetch(`${apiBase}/api/admin/reload/status`, { headers });
    if (!res.ok) throw new Error(`Status failed: HTTP ${res.status}`);
    const data = (await res.json()) as ReloadStatusResponse;
    setTail(data.tail || "");
  }

  function startPolling() {
    stopPolling();
    pollTimer.current = window.setInterval(() => {
      fetchStatusOnce().catch((e) => setErr(String(e)));
    }, 1500);
  }

  async function triggerReload() {
    setErr(null);
    setBusy(true);
    try {
      // kick the updater
      const res = await fetch(`${apiBase}/api/admin/reload`, {
        method: "POST",
        headers,
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`Reload failed: HTTP ${res.status} ${txt}`);
      }
      const _data = (await res.json()) as ReloadStartResponse;

      // immediately start watching logs
      await fetchStatusOnce();
      startPolling();

      // keep polling for a bit; user can stop manually
      setTimeout(() => setBusy(false), 1500);
    } catch (e: any) {
      setBusy(false);
      setErr(String(e));
    }
  }

  async function refreshStatus() {
    setErr(null);
    try {
      await fetchStatusOnce();
    } catch (e: any) {
      setErr(String(e));
    }
  }

  return (
    <section
      className="admin-card"
    >
      <div className="admin-header">
        <div>
          <div className="admin-title">Dev Tools</div>
          <div className="admin-subtitle">
            Triggers <code>/api/admin/reload</code> and shows live updater logs. Remove later for prod.
          </div>
        </div>
        <div className="admin-warning">⚠️ Dev-only</div>
      </div>

      <div className="admin-form">
        <label className="admin-label">
          <div className="admin-label-text">API Base</div>
          <input
            value={apiBase}
            onChange={(e) => setApiBase(e.target.value)}
            placeholder="http://10.0.0.100:9001"
            className="admin-input"
          />
        </label>

        <label className="admin-label">
          <div className="admin-label-text">Admin Token (stored in localStorage)</div>
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Paste SYNTHIA_ADMIN_TOKEN here"
            className="admin-input admin-input-mono"
          />
        </label>

        <div className="admin-actions">
          <button
            onClick={triggerReload}
            disabled={!token.trim() || busy}
            className="admin-btn admin-btn-primary"
            title={!token.trim() ? "Paste token first" : "Trigger reload"}
          >
            {busy ? "Reloading…" : "Reload Core"}
          </button>

          <button
            onClick={refreshStatus}
            disabled={!token.trim()}
            className="admin-btn"
          >
            Refresh Status
          </button>

          <button
            onClick={stopPolling}
            className="admin-btn admin-btn-muted"
          >
            Stop Polling
          </button>
        </div>

        {err && (
          <pre className="admin-error">
            {err}
          </pre>
        )}

        <div>
          <div className="admin-log-label">Updater Log Tail</div>
          <pre
            className="admin-log"
          >
            {tail || "(no log yet)"}
          </pre>
        </div>
      </div>
    </section>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";

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
      style={{
        marginTop: 16,
        padding: 14,
        borderRadius: 16,
        border: "1px solid rgba(255,255,255,0.12)",
        background: "rgba(255,255,255,0.04)",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontWeight: 800, fontSize: 16 }}>Dev Tools</div>
          <div style={{ opacity: 0.75, fontSize: 12 }}>
            Triggers <code>/api/admin/reload</code> and shows live updater logs. Remove later for prod.
          </div>
        </div>
        <div style={{ fontSize: 12, opacity: 0.7 }}>⚠️ Dev-only</div>
      </div>

      <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
        <label style={{ display: "grid", gap: 6 }}>
          <div style={{ fontSize: 12, opacity: 0.8 }}>API Base</div>
          <input
            value={apiBase}
            onChange={(e) => setApiBase(e.target.value)}
            placeholder="http://10.0.0.100:9001"
            style={{
              padding: "10px 12px",
              borderRadius: 12,
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(0,0,0,0.25)",
              color: "white",
            }}
          />
        </label>

        <label style={{ display: "grid", gap: 6 }}>
          <div style={{ fontSize: 12, opacity: 0.8 }}>Admin Token (stored in localStorage)</div>
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Paste SYNTHIA_ADMIN_TOKEN here"
            style={{
              padding: "10px 12px",
              borderRadius: 12,
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(0,0,0,0.25)",
              color: "white",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              fontSize: 12,
            }}
          />
        </label>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button
            onClick={triggerReload}
            disabled={!token.trim() || busy}
            style={{
              padding: "10px 12px",
              borderRadius: 12,
              border: "1px solid rgba(255,255,255,0.15)",
              background: busy ? "rgba(255,255,255,0.06)" : "rgba(255,255,255,0.10)",
              color: "white",
              cursor: busy ? "not-allowed" : "pointer",
            }}
            title={!token.trim() ? "Paste token first" : "Trigger reload"}
          >
            {busy ? "Reloading…" : "Reload Core"}
          </button>

          <button
            onClick={refreshStatus}
            disabled={!token.trim()}
            style={{
              padding: "10px 12px",
              borderRadius: 12,
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.06)",
              color: "white",
              cursor: "pointer",
            }}
          >
            Refresh Status
          </button>

          <button
            onClick={stopPolling}
            style={{
              padding: "10px 12px",
              borderRadius: 12,
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.03)",
              color: "white",
              cursor: "pointer",
              opacity: 0.9,
            }}
          >
            Stop Polling
          </button>
        </div>

        {err && (
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", color: "#ffb3b3", fontSize: 12 }}>
            {err}
          </pre>
        )}

        <div>
          <div style={{ fontSize: 12, opacity: 0.8, marginBottom: 6 }}>Updater Log Tail</div>
          <pre
            style={{
              margin: 0,
              padding: 12,
              borderRadius: 12,
              border: "1px solid rgba(255,255,255,0.12)",
              background: "rgba(0,0,0,0.25)",
              maxHeight: 260,
              overflow: "auto",
              whiteSpace: "pre-wrap",
              fontSize: 12,
            }}
          >
            {tail || "(no log yet)"}
          </pre>
        </div>
      </div>
    </section>
  );
}

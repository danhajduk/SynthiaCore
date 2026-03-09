import { useEffect, useMemo, useState } from "react";

type MqttStatus = {
  connected?: boolean;
  last_error?: string | null;
  last_message_at?: string | null;
  message_count?: number;
};

type MqttSetupSummary = {
  health?: MqttStatus;
  setup?: {
    requires_setup?: boolean;
    setup_complete?: boolean;
    setup_status?: string;
    setup_error?: string | null;
  };
  effective_status?: {
    status?: string;
    reasons?: string[];
    runtime_connected?: boolean;
    authority_ready?: boolean;
    setup_ready?: boolean;
    bootstrap_publish_ready?: boolean;
  };
  reconciliation?: {
    last_reconcile_at?: string | null;
    last_reconcile_reason?: string | null;
    last_reconcile_status?: string | null;
    last_reconcile_error?: string | null;
    last_runtime_state?: string | null;
  };
  bootstrap_publish?: {
    attempts?: number;
    successes?: number;
    last_attempt_at?: string | null;
    last_success_at?: string | null;
    last_error?: string | null;
    published?: boolean;
  };
};

type MqttPrincipal = {
  principal_id: string;
  principal_type: string;
  status: string;
  logical_identity?: string;
  linked_addon_id?: string | null;
  username?: string | null;
  noisy_state?: string;
  updated_at?: string;
};

type AuditEvent = {
  id: number;
  event_type: string;
  status?: string;
  message?: string | null;
  created_at: string;
  payload?: Record<string, unknown>;
};

type ObservabilityEvent = {
  id: number;
  event_type: string;
  source: string;
  severity: string;
  created_at: string;
  metadata?: Record<string, unknown>;
};

type TabKey = "overview" | "principals" | "generic" | "effective" | "runtime" | "audit";

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "principals", label: "Principals" },
  { key: "generic", label: "Generic Users" },
  { key: "effective", label: "Effective Access" },
  { key: "runtime", label: "Runtime Health" },
  { key: "audit", label: "Audit Log" },
];

function displayState(value: unknown): string {
  const raw = String(value || "unknown").trim();
  if (!raw) return "Unknown";
  const normalized = raw.replace(/_/g, " ").toLowerCase();
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function relative(ts?: string | null): string {
  if (!ts) return "-";
  const t = Date.parse(ts);
  if (!Number.isFinite(t)) return ts;
  const deltaS = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (deltaS < 60) return `${deltaS}s ago`;
  if (deltaS < 3600) return `${Math.floor(deltaS / 60)}m ago`;
  if (deltaS < 86400) return `${Math.floor(deltaS / 3600)}h ago`;
  return `${Math.floor(deltaS / 86400)}d ago`;
}

export default function MqttAdminFoundationCard() {
  const [tab, setTab] = useState<TabKey>("overview");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [setupSummary, setSetupSummary] = useState<MqttSetupSummary | null>(null);
  const [principals, setPrincipals] = useState<MqttPrincipal[]>([]);
  const [noisy, setNoisy] = useState<MqttPrincipal[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [obsEvents, setObsEvents] = useState<ObservabilityEvent[]>([]);
  const [selectedPrincipalId, setSelectedPrincipalId] = useState<string>("");
  const [effectiveAccess, setEffectiveAccess] = useState<Record<string, unknown> | null>(null);
  const [effectiveError, setEffectiveError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  const genericUsers = useMemo(
    () => principals.filter((item) => String(item.principal_type).toLowerCase() === "generic_user"),
    [principals],
  );

  async function loadFoundationData() {
    setBusy(true);
    setError(null);
    try {
      const [summaryRes, principalsRes, noisyRes, auditRes, obsRes] = await Promise.all([
        fetch("/api/system/mqtt/setup-summary", { cache: "no-store" }),
        fetch("/api/system/mqtt/principals", { cache: "no-store" }),
        fetch("/api/system/mqtt/noisy-clients", { cache: "no-store" }),
        fetch("/api/system/mqtt/audit?limit=50", { cache: "no-store" }),
        fetch("/api/system/mqtt/observability?limit=50", { cache: "no-store" }),
      ]);
      if (!summaryRes.ok) throw new Error(`setup_summary_http_${summaryRes.status}`);
      if (!principalsRes.ok) throw new Error(`principals_http_${principalsRes.status}`);
      if (!noisyRes.ok) throw new Error(`noisy_http_${noisyRes.status}`);
      if (!auditRes.ok) throw new Error(`audit_http_${auditRes.status}`);
      if (!obsRes.ok) throw new Error(`observability_http_${obsRes.status}`);

      const summaryPayload = (await summaryRes.json()) as MqttSetupSummary;
      const principalsPayload = (await principalsRes.json()) as { items?: MqttPrincipal[] };
      const noisyPayload = (await noisyRes.json()) as { items?: MqttPrincipal[] };
      const auditPayload = (await auditRes.json()) as { items?: AuditEvent[] };
      const obsPayload = (await obsRes.json()) as { items?: ObservabilityEvent[] };

      setSetupSummary(summaryPayload);
      setPrincipals(principalsPayload.items || []);
      setNoisy(noisyPayload.items || []);
      setAuditEvents(auditPayload.items || []);
      setObsEvents(obsPayload.items || []);

      if (!selectedPrincipalId && (principalsPayload.items || []).length > 0) {
        setSelectedPrincipalId((principalsPayload.items || [])[0].principal_id);
      }
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  async function loadEffectiveAccess(principalId: string) {
    const normalized = principalId.trim();
    if (!normalized) {
      setEffectiveAccess(null);
      setEffectiveError(null);
      return;
    }
    setEffectiveError(null);
    try {
      const res = await fetch(`/api/system/mqtt/debug/effective-access/${encodeURIComponent(normalized)}`, { cache: "no-store" });
      if (res.status === 404) {
        setEffectiveAccess(null);
        setEffectiveError("Principal has no effective access (revoked/expired or missing).");
        return;
      }
      if (!res.ok) throw new Error(`effective_access_http_${res.status}`);
      const payload = (await res.json()) as { effective_access?: Record<string, unknown> };
      setEffectiveAccess(payload.effective_access || null);
    } catch (e: any) {
      setEffectiveAccess(null);
      setEffectiveError(e?.message ?? String(e));
    }
  }

  async function triggerRuntimeReload() {
    setActionBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/system/mqtt/reload", { method: "POST", credentials: "include" });
      if (!res.ok) throw new Error(`reload_http_${res.status}`);
      await loadFoundationData();
      if (selectedPrincipalId) {
        await loadEffectiveAccess(selectedPrincipalId);
      }
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setActionBusy(false);
    }
  }

  async function applyNoisyAction(principalId: string, action: string, reason: string) {
    setActionBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/system/mqtt/noisy-clients/${encodeURIComponent(principalId)}/actions/${encodeURIComponent(action)}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      if (!res.ok) throw new Error(`noisy_action_http_${res.status}`);
      await loadFoundationData();
      if (selectedPrincipalId === principalId) {
        await loadEffectiveAccess(principalId);
      }
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setActionBusy(false);
    }
  }

  useEffect(() => {
    void loadFoundationData();
  }, []);

  useEffect(() => {
    if (!selectedPrincipalId) return;
    void loadEffectiveAccess(selectedPrincipalId);
  }, [selectedPrincipalId]);

  return (
    <div className="settings-card settings-mqtt-admin-card">
      <div className="settings-mqtt-admin-top">
        <div>
          <div className="settings-card-title">Embedded MQTT Infrastructure Admin</div>
          <div className="settings-help">Admin-only infrastructure views for authority state, principals, runtime health, and audit data.</div>
        </div>
        <div className="settings-row-actions">
          <button className="settings-btn" onClick={() => void loadFoundationData()} disabled={busy || actionBusy}>
            {busy ? "Refreshing..." : "Refresh MQTT Admin"}
          </button>
          <button className="settings-btn" onClick={() => void triggerRuntimeReload()} disabled={busy || actionBusy}>
            {actionBusy ? "Applying..." : "Run MQTT Reload"}
          </button>
        </div>
      </div>

      <div className="settings-mqtt-status-strip">
        <span className={`settings-pill ${String(setupSummary?.effective_status?.status || "unknown").toLowerCase() === "healthy" ? "" : "settings-pill-warn"}`}>
          Authority {displayState(setupSummary?.effective_status?.status)}
        </span>
        <span className="settings-pill">Runtime {setupSummary?.effective_status?.runtime_connected ? "Connected" : "Disconnected"}</span>
        <span className="settings-pill">
          Bootstrap {setupSummary?.bootstrap_publish?.published ? "Published" : "Pending"}
        </span>
        <span className="settings-pill">Last runtime error {setupSummary?.health?.last_error || "none"}</span>
      </div>

      {error && <div className="settings-error">MQTT admin load failed: {error}</div>}

      <div className="settings-mqtt-tabs" role="tablist" aria-label="MQTT admin views">
        {TABS.map((item) => (
          <button
            key={item.key}
            className={`settings-btn ${tab === item.key ? "settings-mqtt-tab-active" : ""}`}
            onClick={() => setTab(item.key)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="settings-kv-grid">
          <div className="settings-kv-item">
            <div className="settings-label-text">Authority status</div>
            <div>{displayState(setupSummary?.effective_status?.status)}</div>
            <div className="settings-help">Reasons {(setupSummary?.effective_status?.reasons || []).join(" | ") || "none"}</div>
          </div>
          <div className="settings-kv-item">
            <div className="settings-label-text">Setup state</div>
            <div>{displayState(setupSummary?.setup?.setup_status)}</div>
            <div className="settings-help">
              {setupSummary?.setup?.setup_complete ? "Complete" : "Incomplete"} • {setupSummary?.setup?.requires_setup ? "Required" : "Optional"}
            </div>
          </div>
          <div className="settings-kv-item">
            <div className="settings-label-text">Runtime health</div>
            <div>{setupSummary?.health?.connected ? "Connected" : "Disconnected"}</div>
            <div className="settings-help">Last error {setupSummary?.health?.last_error || "none"}</div>
          </div>
          <div className="settings-kv-item">
            <div className="settings-label-text">Last reconcile</div>
            <div>{displayState(setupSummary?.reconciliation?.last_reconcile_status)}</div>
            <div className="settings-help">Reason {setupSummary?.reconciliation?.last_reconcile_reason || "-"}</div>
          </div>
        </div>
      )}

      {tab === "principals" && (
        <div className="settings-mqtt-table-wrap">
          <table className="settings-mqtt-table">
            <thead>
              <tr>
                <th>Principal</th>
                <th>Type</th>
                <th>Status</th>
                <th>Noisy</th>
                <th>Linked</th>
              </tr>
            </thead>
            <tbody>
              {principals.map((item) => (
                <tr key={item.principal_id}>
                  <td>{item.principal_id}</td>
                  <td>{item.principal_type}</td>
                  <td>{item.status}</td>
                  <td>{item.noisy_state || "normal"}</td>
                  <td>{item.linked_addon_id || item.username || "-"}</td>
                </tr>
              ))}
              {!principals.length && (
                <tr>
                  <td colSpan={5}>No principals found.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === "generic" && (
        <div className="settings-mqtt-table-wrap">
          <table className="settings-mqtt-table">
            <thead>
              <tr>
                <th>Principal</th>
                <th>Identity</th>
                <th>Status</th>
                <th>Noisy</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {genericUsers.map((item) => (
                <tr key={item.principal_id}>
                  <td>{item.principal_id}</td>
                  <td>{item.logical_identity || "-"}</td>
                  <td>{item.status}</td>
                  <td>{item.noisy_state || "normal"}</td>
                  <td>
                    <div className="settings-row-actions">
                      <button
                        className="settings-btn"
                        disabled={busy || actionBusy}
                        onClick={() => void applyNoisyAction(item.principal_id, "mark_watch", "ui_watch")}
                      >
                        Watch
                      </button>
                      <button
                        className="settings-btn"
                        disabled={busy || actionBusy}
                        onClick={() => void applyNoisyAction(item.principal_id, "quarantine", "ui_quarantine")}
                      >
                        Quarantine
                      </button>
                      <button
                        className="settings-btn"
                        disabled={busy || actionBusy}
                        onClick={() => void applyNoisyAction(item.principal_id, "clear", "ui_clear")}
                      >
                        Clear
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!genericUsers.length && (
                <tr>
                  <td colSpan={5}>No generic users found.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === "effective" && (
        <div className="settings-mqtt-effective">
          <label className="settings-label">
            <div className="settings-label-text">Principal</div>
            <select
              value={selectedPrincipalId}
              onChange={(e) => setSelectedPrincipalId(e.target.value)}
              className="settings-select-input"
            >
              <option value="">Select principal</option>
              {principals.map((item) => (
                <option key={item.principal_id} value={item.principal_id}>
                  {item.principal_id}
                </option>
              ))}
            </select>
          </label>
          {effectiveError && <div className="settings-help">{effectiveError}</div>}
          <pre className="settings-pre">{JSON.stringify(effectiveAccess || {}, null, 2)}</pre>
        </div>
      )}

      {tab === "runtime" && (
        <div className="settings-kv-grid">
          <div className="settings-kv-item">
            <div className="settings-label-text">Health</div>
            <div>{setupSummary?.effective_status?.runtime_connected ? "Connected" : "Disconnected"}</div>
            <div className="settings-help">Last runtime error {setupSummary?.health?.last_error || "none"}</div>
          </div>
          <div className="settings-kv-item">
            <div className="settings-label-text">Last apply/reload result</div>
            <div>{displayState(setupSummary?.reconciliation?.last_reconcile_status)}</div>
            <div className="settings-help">Error {setupSummary?.reconciliation?.last_reconcile_error || "none"}</div>
          </div>
          <div className="settings-kv-item">
            <div className="settings-label-text">Last apply reason</div>
            <div>{setupSummary?.reconciliation?.last_reconcile_reason || "-"}</div>
            <div className="settings-help">At {relative(setupSummary?.reconciliation?.last_reconcile_at)}</div>
          </div>
          <div className="settings-kv-item">
            <div className="settings-label-text">Bootstrap publish</div>
            <div>{setupSummary?.bootstrap_publish?.published ? "Published" : "Pending"}</div>
            <div className="settings-help">
              Attempts {Number(setupSummary?.bootstrap_publish?.attempts || 0)} • Last error {setupSummary?.bootstrap_publish?.last_error || "none"}
            </div>
          </div>
        </div>
      )}

      {tab === "audit" && (
        <div className="settings-mqtt-audit-grid">
          <div>
            <div className="settings-card-title">Authority Audit</div>
            <pre className="settings-pre">{JSON.stringify(auditEvents, null, 2)}</pre>
          </div>
          <div>
            <div className="settings-card-title">Observability Events</div>
            <pre className="settings-pre">{JSON.stringify(obsEvents, null, 2)}</pre>
          </div>
        </div>
      )}

      {!!noisy.length && (
        <div className="settings-help">
          Noisy clients: {noisy.map((item) => `${item.principal_id} (${item.noisy_state || "normal"})`).join(" | ")}
        </div>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import "./settings.css";

type StatsAddon = {
  addon_id: string;
  count: number;
  states: Record<string, number>;
  avg_runtime_s: number | null;
  p95_runtime_s: number | null;
  avg_queue_wait_s?: number | null;
};

type StatsResponse = {
  ok: boolean;
  range?: { from: string; to: string; days: number };
  total?: number;
  totals_by_state?: Record<string, number>;
  success_rate?: number | null;
  avg_queue_wait_s?: number | null;
  addons?: StatsAddon[];
  error?: string;
};

const RETENTION_DAYS = 30;

export default function SettingsStatistics() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadStats() {
    setErr(null);
    try {
      const res = await fetch(`/api/system/scheduler/history/stats?days=${RETENTION_DAYS}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = (await res.json()) as StatsResponse;
      if (!payload.ok) throw new Error(payload.error || "stats_disabled");
      setStats(payload);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
      setStats(null);
    }
  }

  async function cleanupHistory() {
    setErr(null);
    setBusy(true);
    try {
      const res = await fetch(`/api/system/scheduler/history/cleanup?days=${RETENTION_DAYS}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await loadStats();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    loadStats();
  }, []);

  return (
    <div>
      <h1 className="settings-title">Settings / Statistics</h1>
      <p className="settings-muted">
        Job history is stored for {RETENTION_DAYS} days (auto-cleaned daily).
      </p>

      <div className="settings-row">
        <div />
        <div className="settings-row-actions">
          <button className="settings-btn" onClick={loadStats}>Refresh</button>
          <button className="settings-btn" onClick={cleanupHistory} disabled={busy}>
            Clean history
          </button>
        </div>
      </div>

      {err && <div className="settings-error">Failed to load stats: {err}</div>}

      {stats && stats.totals_by_state && (
        <>
          <div className="settings-stats-grid">
            <div className="settings-stats-card">
              <div className="settings-stats-title">Totals</div>
              <div className="settings-stats-kv">
                <span>Total</span>
                <strong>{stats.total ?? 0}</strong>
              </div>
              <div className="settings-stats-kv">
                <span>Success rate</span>
                <strong>
                  {typeof stats.success_rate === "number"
                    ? `${(stats.success_rate * 100).toFixed(1)}%`
                    : "-"}
                </strong>
              </div>
              <div className="settings-stats-kv">
                <span>Avg queue wait (s)</span>
                <strong>
                  {typeof stats.avg_queue_wait_s === "number"
                    ? stats.avg_queue_wait_s.toFixed(2)
                    : "-"}
                </strong>
              </div>
              {Object.entries(stats.totals_by_state).map(([state, count]) => (
                <div key={state} className="settings-stats-kv">
                  <span>{state}</span>
                  <strong>{count}</strong>
                </div>
              ))}
            </div>
            <div className="settings-stats-card">
              <div className="settings-stats-title">Range</div>
              <div className="settings-stats-kv">
                <span>From</span>
                <strong>{stats.range?.from ? new Date(stats.range.from).toLocaleString() : "-"}</strong>
              </div>
              <div className="settings-stats-kv">
                <span>To</span>
                <strong>{stats.range?.to ? new Date(stats.range.to).toLocaleString() : "-"}</strong>
              </div>
              <div className="settings-stats-kv">
                <span>Days</span>
                <strong>{stats.range?.days ?? RETENTION_DAYS}</strong>
              </div>
            </div>
          </div>

          <h2>Per Addon</h2>
          <div className="settings-stats-table">
            <div className="settings-stats-header">
              <span>Addon</span>
              <span>Total</span>
              <span>Completed</span>
              <span>Failed</span>
              <span>Expired</span>
              <span>Avg queue wait (s)</span>
              <span>Avg runtime (s)</span>
              <span>P95 runtime (s)</span>
            </div>
            {(stats.addons || []).map((addon) => (
              <div key={addon.addon_id} className="settings-stats-row">
                <span className="settings-mono">{addon.addon_id}</span>
                <span>{addon.count}</span>
                <span>{addon.states?.completed ?? 0}</span>
                <span>{addon.states?.failed ?? 0}</span>
                <span>{addon.states?.expired ?? 0}</span>
                <span>{addon.avg_queue_wait_s ? addon.avg_queue_wait_s.toFixed(2) : "-"}</span>
                <span>{addon.avg_runtime_s ? addon.avg_runtime_s.toFixed(2) : "-"}</span>
                <span>{addon.p95_runtime_s ? addon.p95_runtime_s.toFixed(2) : "-"}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

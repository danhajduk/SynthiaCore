import React, { useEffect, useMemo, useState } from "react";
import "./system-stats-widget.css";

type SystemStats = {
  timestamp: number;
  hostname: string;
  uptime_s: number;
  load: { load1: number; load5: number; load15: number };
  cpu: { percent_total: number; percent_per_cpu: number[]; cores_logical: number; cores_physical?: number };
  mem: { total: number; available: number; used: number; free: number; percent: number };
  swap: { total: number; used: number; free: number; percent: number };
  disks: Record<string, { total: number; used: number; free: number; percent: number }>;
  net: {
    total: { bytes_sent: number; bytes_recv: number };
    total_rate?: { tx_Bps: number; rx_Bps: number } | null;
    per_iface_rate?: Record<string, { tx_Bps: number; rx_Bps: number }> | null;
  };
  api: {
    window_s: number;
    rps: number;
    inflight: number;
    latency_ms_avg: number;
    latency_ms_p95: number;
    error_rate: number;
    top_paths: [string, number][];
    top_clients: [string, number][];
  };
  busy_rating: number;
};

function clamp(x: number, lo = 0, hi = 100) {
  return Math.max(lo, Math.min(hi, x));
}

function fmtBytes(n: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let x = n;
  let i = 0;
  while (x >= 1024 && i < units.length - 1) {
    x /= 1024;
    i++;
  }
  return `${x.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
function fmtBps(n: number): string {
  return `${fmtBytes(n)}/s`;
}
function fmtUptime(sec: number): string {
  const h = sec / 3600;
  if (h < 48) return `${h.toFixed(1)}h`;
  const d = Math.floor(h / 24);
  const rem = h - d * 24;
  return `${d}d ${rem.toFixed(0)}h`;
}

function busyStyle(busy: number) {
  if (busy >= 8) return { label: "HOT", className: "stats-badge-hot" };
  if (busy >= 6) return { label: "BUSY", className: "stats-badge-busy" };
  if (busy >= 3) return { label: "ACTIVE", className: "stats-badge-active" };
  return { label: "IDLE", className: "stats-badge-idle" };
}

function pctClass(pct: number) {
  const rounded = Math.round(clamp(pct) / 5) * 5;
  return `pct-${Math.max(0, Math.min(100, rounded))}`;
}

export default function SystemStatsWidget() {
  const [data, setData] = useState<SystemStats | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showApiDetails, setShowApiDetails] = useState(false);
  const [showRaw, setShowRaw] = useState(false);

  async function load() {
    try {
      setErr(null);
      const res = await fetch("/api/system/stats/current", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData((await res.json()) as SystemStats);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const busy = data?.busy_rating ?? 0;
  const badge = useMemo(() => busyStyle(busy), [busy]);

  if (err) {
    return (
      <div className="stats-panel">
        <div className="stats-header-row">
          <div>
            <div className="stats-title">System Health</div>
            <div className="stats-subtitle">Live system + API metrics</div>
          </div>
          <button className="stats-btn" onClick={load}>Retry</button>
        </div>
        <div className="stats-error-box">
          Failed to load: {err}
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="stats-panel">
        <div className="stats-title">System Health</div>
        <div className="stats-subtitle">Loading…</div>
      </div>
    );
  }

  const lastSeen = new Date(data.timestamp * 1000).toLocaleTimeString();
  const cpuPct = data.cpu.percent_total;
  const memPct = data.mem.percent;
  const load1 = data.load.load1;
  const rx = data.net.total_rate?.rx_Bps ?? 0;
  const tx = data.net.total_rate?.tx_Bps ?? 0;

  return (
    <div className="stats-panel">
      <div className="stats-header-row">
        <div>
          <div className="stats-title">System Health</div>
          <div className="stats-subtitle">
            <span className="stats-mono stats-mono-small">{data.hostname}</span>
            <span className="stats-divider">•</span>
            uptime {fmtUptime(data.uptime_s)}
            <span className="stats-divider">•</span>
            updated {lastSeen}
          </div>
        </div>

        <div className={`stats-badge ${badge.className}`}>
          <span>{badge.label}</span>
          <span className="stats-dot">•</span>
          <span>{busy.toFixed(1)}/10</span>
        </div>
      </div>

      <div className="stats-grid-4">
        <Kpi title="CPU" value={`${cpuPct.toFixed(1)}%`} sub={`cores ${data.cpu.cores_logical}`} pct={cpuPct} />
        <Kpi title="Memory" value={`${memPct.toFixed(1)}%`} sub={`${fmtBytes(data.mem.used)} used`} pct={memPct} />
        <Kpi title="Load" value={load1.toFixed(2)} sub={`${data.load.load5.toFixed(2)} / ${data.load.load15.toFixed(2)}`} pct={clamp((load1 / Math.max(1, data.cpu.cores_logical)) * 100)} />
        <Kpi title="Network" value={data.net.total_rate ? `↓ ${fmtBps(rx)}` : "—"} sub={data.net.total_rate ? `↑ ${fmtBps(tx)}` : "warming up"} pct={data.net.total_rate ? clamp((Math.log10(rx + tx + 1) / 7) * 100) : 0} />
      </div>

      <div className="stats-grid-2">
        <div className="stats-card">
          <div className="stats-row-between">
            <div className="stats-label">Disks</div>
          </div>
          <div className="stats-disks">
            {Object.entries(data.disks).map(([mnt, d]) => (
              <div key={mnt}>
                <div className="stats-row-between">
                  <div className="stats-mono stats-mono-small">{mnt}</div>
                  <div className="stats-sub">{d.percent.toFixed(1)}%</div>
                </div>
                <div className="stats-bar-outer">
                  <div className={`stats-bar-inner ${pctClass(d.percent)}`} />
                </div>
                <div className="stats-disk-sub">
                  {fmtBytes(d.used)} / {fmtBytes(d.total)}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="stats-card">
          <div className="stats-row-between">
            <div className="stats-label">API (last {data.api.window_s}s)</div>
            <button className="stats-btn" onClick={() => setShowApiDetails(v => !v)}>
              {showApiDetails ? "Hide details" : "Show details"}
            </button>
          </div>

          <div className="stats-small-grid">
            <Mini label="RPS" value={data.api.rps.toFixed(2)} />
            <Mini label="Inflight" value={`${data.api.inflight}`} />
            <Mini label="p95" value={`${Math.round(data.api.latency_ms_p95)} ms`} />
            <Mini label="Errors" value={`${(data.api.error_rate * 100).toFixed(1)}%`} />
          </div>

          {showApiDetails && (
            <div className="stats-api-details">
              <Top title="Top paths" items={data.api.top_paths} empty="No tracked requests (stats endpoint excluded)." />
              <Top title="Top clients" items={data.api.top_clients} empty="No tracked clients yet." />
            </div>
          )}
        </div>
      </div>

      <div className="stats-raw-toggle">
        <button className="stats-btn" onClick={() => setShowRaw(v => !v)}>{showRaw ? "Hide raw JSON" : "Show raw JSON"}</button>
      </div>

      {showRaw && <pre className="stats-pre">{JSON.stringify(data, null, 2)}</pre>}
    </div>
  );
}

function Kpi(props: { title: string; value: string; sub: string; pct: number }) {
  return (
    <div className="stats-card">
      <div className="stats-label">{props.title}</div>
      <div className="stats-value">{props.value}</div>
      <div className="stats-sub">{props.sub}</div>
      <div className="stats-bar-outer">
        <div className={`stats-bar-inner ${pctClass(props.pct)}`} />
      </div>
    </div>
  );
}

function Mini(props: { label: string; value: string }) {
  return (
    <div className="stats-mini">
      <div className="stats-mini-label">{props.label}</div>
      <div className="stats-mini-value">{props.value}</div>
    </div>
  );
}

function Top(props: { title: string; items: [string, number][]; empty: string }) {
  return (
    <div className="stats-mini">
      <div className="stats-mini-label">{props.title}</div>
      <div className="stats-list">
        {props.items.slice(0, 8).map(([k, v]) => (
          <div key={k} className="stats-list-row">
            <span className="stats-mono stats-list-key">{k}</span>
            <span className="stats-sub">{v}</span>
          </div>
        ))}
        {props.items.length === 0 && <div className="stats-list-empty">{props.empty}</div>}
      </div>
    </div>
  );
}

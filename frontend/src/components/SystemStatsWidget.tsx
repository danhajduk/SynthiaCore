import React, { useEffect, useMemo, useState } from "react";

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
  // returns {label, bg, border, text}
  if (busy >= 8) return { label: "HOT", bg: "rgba(220,38,38,0.15)", border: "rgba(220,38,38,0.35)", text: "#fecaca" };
  if (busy >= 6) return { label: "BUSY", bg: "rgba(249,115,22,0.15)", border: "rgba(249,115,22,0.35)", text: "#fed7aa" };
  if (busy >= 3) return { label: "ACTIVE", bg: "rgba(234,179,8,0.12)", border: "rgba(234,179,8,0.30)", text: "#fef3c7" };
  return { label: "IDLE", bg: "rgba(16,185,129,0.12)", border: "rgba(16,185,129,0.30)", text: "#d1fae5" };
}

const styles = {
  panel: {
    border: "1px solid rgba(255,255,255,0.10)",
    background: "rgba(255,255,255,0.04)",
    borderRadius: 16,
    padding: 16,
  } as React.CSSProperties,
  headerRow: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
    flexWrap: "wrap",
  } as React.CSSProperties,
  title: {
    fontSize: 14,
    fontWeight: 700,
    margin: 0,
  } as React.CSSProperties,
  subtitle: {
    marginTop: 4,
    fontSize: 12,
    opacity: 0.7,
  } as React.CSSProperties,
  badge: (busy: number): React.CSSProperties => {
    const b = busyStyle(busy);
    return {
      display: "inline-flex",
      alignItems: "center",
      gap: 8,
      padding: "6px 10px",
      borderRadius: 999,
      border: `1px solid ${b.border}`,
      background: b.bg,
      color: b.text,
      fontSize: 12,
      fontWeight: 700,
      whiteSpace: "nowrap",
    };
  },
  grid4: {
    display: "grid",
    gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
    gap: 12,
    marginTop: 14,
  } as React.CSSProperties,
  grid2: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 12,
    marginTop: 12,
  } as React.CSSProperties,
  card: {
    border: "1px solid rgba(255,255,255,0.10)",
    background: "rgba(0,0,0,0.18)",
    borderRadius: 14,
    padding: 14,
    minWidth: 0,
  } as React.CSSProperties,
  label: {
    fontSize: 11,
    fontWeight: 700,
    opacity: 0.75,
    letterSpacing: 0.2,
  } as React.CSSProperties,
  value: {
    marginTop: 6,
    fontSize: 22,
    fontWeight: 800,
  } as React.CSSProperties,
  sub: {
    marginTop: 2,
    fontSize: 12,
    opacity: 0.7,
  } as React.CSSProperties,
  barOuter: {
    marginTop: 10,
    height: 8,
    width: "100%",
    borderRadius: 999,
    background: "rgba(255,255,255,0.10)",
    overflow: "hidden",
  } as React.CSSProperties,
  barInner: (pct: number): React.CSSProperties => ({
    height: "100%",
    width: `${clamp(pct)}%`,
    borderRadius: 999,
    background: "rgba(255,255,255,0.55)",
  }),
  rowBetween: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
  } as React.CSSProperties,
  mono: {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
  } as React.CSSProperties,
  btn: {
    border: "1px solid rgba(255,255,255,0.12)",
    background: "rgba(255,255,255,0.04)",
    color: "inherit",
    borderRadius: 10,
    padding: "6px 10px",
    fontSize: 12,
    fontWeight: 700,
    cursor: "pointer",
  } as React.CSSProperties,
  smallGrid2: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 10,
    marginTop: 10,
  } as React.CSSProperties,
  mini: {
    border: "1px solid rgba(255,255,255,0.10)",
    background: "rgba(255,255,255,0.03)",
    borderRadius: 12,
    padding: "8px 10px",
  } as React.CSSProperties,
  miniLabel: { fontSize: 10, fontWeight: 800, opacity: 0.7 } as React.CSSProperties,
  miniValue: { marginTop: 3, fontSize: 14, fontWeight: 800 } as React.CSSProperties,
  list: { marginTop: 8, display: "flex", flexDirection: "column", gap: 6 } as React.CSSProperties,
  listRow: { display: "flex", justifyContent: "space-between", gap: 10, fontSize: 12 } as React.CSSProperties,
  pre: {
    marginTop: 10,
    maxHeight: 380,
    overflow: "auto",
    border: "1px solid rgba(255,255,255,0.10)",
    background: "rgba(0,0,0,0.35)",
    borderRadius: 14,
    padding: 12,
    fontSize: 11,
    opacity: 0.85,
  } as React.CSSProperties,
};

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
      <div style={styles.panel}>
        <div style={styles.headerRow}>
          <div>
            <div style={styles.title}>System Health</div>
            <div style={styles.subtitle}>Live system + API metrics</div>
          </div>
          <button style={styles.btn} onClick={load}>Retry</button>
        </div>
        <div style={{ marginTop: 12, padding: 10, borderRadius: 12, border: "1px solid rgba(220,38,38,0.35)", background: "rgba(220,38,38,0.12)", color: "#fecaca", fontSize: 13 }}>
          Failed to load: {err}
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div style={styles.panel}>
        <div style={styles.title}>System Health</div>
        <div style={styles.subtitle}>Loading…</div>
      </div>
    );
  }

  const lastSeen = new Date(data.timestamp * 1000).toLocaleTimeString();
  const cpuPct = data.cpu.percent_total;
  const memPct = data.mem.percent;
  const load1 = data.load.load1;
  const rx = data.net.total_rate?.rx_Bps ?? 0;
  const tx = data.net.total_rate?.tx_Bps ?? 0;

  // Make grids responsive without Tailwind
  const grid4 = {
    ...styles.grid4,
    gridTemplateColumns: window.innerWidth < 900 ? "repeat(2, minmax(0, 1fr))" : "repeat(4, minmax(0, 1fr))",
  } as React.CSSProperties;

  const grid2 = {
    ...styles.grid2,
    gridTemplateColumns: window.innerWidth < 900 ? "repeat(1, minmax(0, 1fr))" : "repeat(2, minmax(0, 1fr))",
  } as React.CSSProperties;

  return (
    <div style={styles.panel}>
      <div style={styles.headerRow}>
        <div>
          <div style={styles.title}>System Health</div>
          <div style={styles.subtitle}>
            <span style={{ ...styles.mono, opacity: 0.85 }}>{data.hostname}</span>
            <span style={{ opacity: 0.35, margin: "0 8px" }}>•</span>
            uptime {fmtUptime(data.uptime_s)}
            <span style={{ opacity: 0.35, margin: "0 8px" }}>•</span>
            updated {lastSeen}
          </div>
        </div>

        <div style={styles.badge(busy)}>
          <span>{badge.label}</span>
          <span style={{ opacity: 0.6 }}>•</span>
          <span>{busy.toFixed(1)}/10</span>
        </div>
      </div>

      <div style={grid4}>
        <Kpi title="CPU" value={`${cpuPct.toFixed(1)}%`} sub={`cores ${data.cpu.cores_logical}`} pct={cpuPct} />
        <Kpi title="Memory" value={`${memPct.toFixed(1)}%`} sub={`${fmtBytes(data.mem.used)} used`} pct={memPct} />
        <Kpi title="Load" value={load1.toFixed(2)} sub={`${data.load.load5.toFixed(2)} / ${data.load.load15.toFixed(2)}`} pct={clamp((load1 / Math.max(1, data.cpu.cores_logical)) * 100)} />
        <Kpi title="Network" value={data.net.total_rate ? `↓ ${fmtBps(rx)}` : "—"} sub={data.net.total_rate ? `↑ ${fmtBps(tx)}` : "warming up"} pct={data.net.total_rate ? clamp((Math.log10(rx + tx + 1) / 7) * 100) : 0} />
      </div>

      <div style={grid2}>
        <div style={styles.card}>
          <div style={styles.rowBetween}>
            <div style={styles.label}>Disks</div>
          </div>
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 12 }}>
            {Object.entries(data.disks).map(([mnt, d]) => (
              <div key={mnt}>
                <div style={styles.rowBetween}>
                  <div style={{ ...styles.mono, fontSize: 12, opacity: 0.85 }}>{mnt}</div>
                  <div style={{ fontSize: 12, opacity: 0.75 }}>{d.percent.toFixed(1)}%</div>
                </div>
                <div style={styles.barOuter}>
                  <div style={styles.barInner(d.percent)} />
                </div>
                <div style={{ marginTop: 4, fontSize: 11, opacity: 0.6 }}>
                  {fmtBytes(d.used)} / {fmtBytes(d.total)}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={styles.card}>
          <div style={styles.rowBetween}>
            <div style={styles.label}>API (last {data.api.window_s}s)</div>
            <button style={styles.btn} onClick={() => setShowApiDetails(v => !v)}>
              {showApiDetails ? "Hide details" : "Show details"}
            </button>
          </div>

          <div style={styles.smallGrid2}>
            <Mini label="RPS" value={data.api.rps.toFixed(2)} />
            <Mini label="Inflight" value={`${data.api.inflight}`} />
            <Mini label="p95" value={`${Math.round(data.api.latency_ms_p95)} ms`} />
            <Mini label="Errors" value={`${(data.api.error_rate * 100).toFixed(1)}%`} />
          </div>

          {showApiDetails && (
            <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <Top title="Top paths" items={data.api.top_paths} empty="No tracked requests (stats endpoint excluded)." />
              <Top title="Top clients" items={data.api.top_clients} empty="No tracked clients yet." />
            </div>
          )}
        </div>
      </div>

      <div style={{ marginTop: 12, display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button style={styles.btn} onClick={() => setShowRaw(v => !v)}>{showRaw ? "Hide raw JSON" : "Show raw JSON"}</button>
      </div>

      {showRaw && <pre style={styles.pre}>{JSON.stringify(data, null, 2)}</pre>}
    </div>
  );
}

function Kpi(props: { title: string; value: string; sub: string; pct: number }) {
  return (
    <div style={styles.card}>
      <div style={styles.label}>{props.title}</div>
      <div style={styles.value}>{props.value}</div>
      <div style={styles.sub}>{props.sub}</div>
      <div style={styles.barOuter}>
        <div style={styles.barInner(props.pct)} />
      </div>
    </div>
  );
}

function Mini(props: { label: string; value: string }) {
  return (
    <div style={styles.mini}>
      <div style={styles.miniLabel}>{props.label}</div>
      <div style={styles.miniValue}>{props.value}</div>
    </div>
  );
}

function Top(props: { title: string; items: [string, number][]; empty: string }) {
  return (
    <div style={{ ...styles.mini, padding: 10 }}>
      <div style={{ ...styles.miniLabel, fontSize: 11 }}>{props.title}</div>
      <div style={styles.list}>
        {props.items.slice(0, 8).map(([k, v]) => (
          <div key={k} style={styles.listRow}>
            <span style={{ ...styles.mono, opacity: 0.85, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{k}</span>
            <span style={{ opacity: 0.75 }}>{v}</span>
          </div>
        ))}
        {props.items.length === 0 && <div style={{ fontSize: 12, opacity: 0.55 }}>{props.empty}</div>}
      </div>
    </div>
  );
}

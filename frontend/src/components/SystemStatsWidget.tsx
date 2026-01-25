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

function busyBadge(busy: number) {
  if (busy >= 8) return { label: "HOT", cls: "bg-red-600/20 text-red-200 border-red-500/30" };
  if (busy >= 6) return { label: "BUSY", cls: "bg-orange-600/20 text-orange-200 border-orange-500/30" };
  if (busy >= 3) return { label: "ACTIVE", cls: "bg-yellow-500/20 text-yellow-100 border-yellow-400/30" };
  return { label: "IDLE", cls: "bg-emerald-600/20 text-emerald-100 border-emerald-400/30" };
}

function clampPct(x: number) {
  return Math.max(0, Math.min(100, x));
}

export default function SystemStatsWidget() {
  const [data, setData] = useState<SystemStats | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState(false);
  const [showApiLists, setShowApiLists] = useState(false);

  async function load() {
    try {
      setErr(null);
      const res = await fetch("/api/system/stats/current", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as SystemStats;
      setData(json);
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
  const badge = useMemo(() => busyBadge(busy), [busy]);

  if (err) {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold">System Health</div>
            <div className="text-xs text-white/60">Live system + API metrics</div>
          </div>
          <button
            className="rounded-lg border border-white/10 bg-white/5 px-3 py-1 text-xs hover:bg-white/10"
            onClick={load}
          >
            Retry
          </button>
        </div>
        <div className="mt-3 rounded-xl border border-red-500/30 bg-red-600/10 p-3 text-sm text-red-200">
          Failed to load: {err}
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-4 shadow-sm">
        <div className="text-sm font-semibold">System Health</div>
        <div className="mt-2 text-sm text-white/60">Loading…</div>
      </div>
    );
  }

  const lastSeen = new Date(data.timestamp * 1000).toLocaleTimeString();
  const cpuPct = data.cpu.percent_total;
  const memPct = data.mem.percent;
  const load1 = data.load.load1;
  const netRx = data.net.total_rate?.rx_Bps ?? 0;
  const netTx = data.net.total_rate?.tx_Bps ?? 0;

  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4 shadow-sm">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">System Health</div>
          <div className="mt-0.5 text-xs text-white/60">
            <span className="font-mono">{data.hostname}</span>
            <span className="mx-2 opacity-40">•</span>
            uptime {fmtUptime(data.uptime_s)}
            <span className="mx-2 opacity-40">•</span>
            updated {lastSeen}
          </div>
        </div>

        <div className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${badge.cls}`}>
          <span>{badge.label}</span>
          <span className="opacity-70">•</span>
          <span>{busy.toFixed(1)}/10</span>
        </div>
      </div>

      {/* KPI cards */}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="CPU"
          value={`${cpuPct.toFixed(1)}%`}
          sub={`cores ${data.cpu.cores_logical}`}
          barPct={cpuPct}
        />
        <KpiCard
          title="Memory"
          value={`${memPct.toFixed(1)}%`}
          sub={`${fmtBytes(data.mem.used)} used`}
          barPct={memPct}
        />
        <KpiCard
          title="Load"
          value={load1.toFixed(2)}
          sub={`${data.load.load5.toFixed(2)} / ${data.load.load15.toFixed(2)}`}
          // load isn't a %; map gently to a bar (per-core-ish look)
          barPct={clampPct((load1 / Math.max(1, data.cpu.cores_logical)) * 100)}
          barLabel="per-core"
        />
        <KpiCard
          title="Network"
          value={data.net.total_rate ? `↓ ${fmtBps(netRx)}` : "—"}
          sub={data.net.total_rate ? `↑ ${fmtBps(netTx)}` : "warming up"}
          barPct={data.net.total_rate ? clampPct((Math.log10(netRx + netTx + 1) / 7) * 100) : 0}
          barLabel="activity"
        />
      </div>

      {/* Disks + API */}
      <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
          <div className="text-xs font-semibold text-white/70">Disks</div>
          <div className="mt-3 space-y-3">
            {Object.entries(data.disks).map(([mnt, d]) => (
              <div key={mnt}>
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-white/80">{mnt}</span>
                  <span className="text-white/70">{d.percent.toFixed(1)}%</span>
                </div>
                <div className="mt-1 h-2 w-full rounded bg-white/10">
                  <div
                    className="h-2 rounded bg-white/60"
                    style={{ width: `${clampPct(d.percent)}%` }}
                  />
                </div>
                <div className="mt-1 text-[11px] text-white/50">
                  {fmtBytes(d.used)} used / {fmtBytes(d.total)} total
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
          <div className="flex items-center justify-between">
            <div className="text-xs font-semibold text-white/70">API (last {data.api.window_s}s)</div>
            <button
              className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] hover:bg-white/10"
              onClick={() => setShowApiLists((v) => !v)}
            >
              {showApiLists ? "Hide details" : "Show details"}
            </button>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2">
            <MiniStat label="RPS" value={data.api.rps.toFixed(2)} />
            <MiniStat label="Inflight" value={String(data.api.inflight)} />
            <MiniStat label="p95" value={`${Math.round(data.api.latency_ms_p95)} ms`} />
            <MiniStat label="Errors" value={`${(data.api.error_rate * 100).toFixed(1)}%`} />
          </div>

          {showApiLists && (
            <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
              <TopList title="Top paths" items={data.api.top_paths} emptyHint="No tracked requests (stats endpoint excluded)." />
              <TopList title="Top clients" items={data.api.top_clients} emptyHint="No tracked clients yet." />
            </div>
          )}
        </div>
      </div>

      {/* Details */}
      <div className="mt-4">
        <button
          className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-white/80 hover:bg-white/10"
          onClick={() => setShowDetails((v) => !v)}
        >
          {showDetails ? "Hide raw details" : "Show raw details"}
        </button>

        {showDetails && (
          <pre className="mt-3 max-h-[380px] overflow-auto rounded-2xl border border-white/10 bg-black/40 p-3 text-[11px] text-white/70">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

function KpiCard(props: {
  title: string;
  value: string;
  sub?: string;
  barPct: number;
  barLabel?: string;
}) {
  const pct = clampPct(props.barPct);
  return (
    <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold text-white/70">{props.title}</div>
        {props.barLabel && <div className="text-[10px] text-white/40">{props.barLabel}</div>}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight">{props.value}</div>
      {props.sub && <div className="mt-0.5 text-xs text-white/60">{props.sub}</div>}
      <div className="mt-3 h-2 w-full rounded bg-white/10">
        <div className="h-2 rounded bg-white/60" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function MiniStat(props: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
      <div className="text-[10px] font-semibold text-white/60">{props.label}</div>
      <div className="mt-0.5 text-sm font-semibold text-white/90">{props.value}</div>
    </div>
  );
}

function TopList(props: { title: string; items: [string, number][]; emptyHint: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
      <div className="text-[11px] font-semibold text-white/70">{props.title}</div>
      <div className="mt-2 space-y-1">
        {props.items.slice(0, 8).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-3 text-xs">
            <span className="truncate font-mono text-white/80">{k}</span>
            <span className="shrink-0 text-white/60">{v}</span>
          </div>
        ))}
        {props.items.length === 0 && <div className="text-xs text-white/40">{props.emptyHint}</div>}
      </div>
    </div>
  );
}

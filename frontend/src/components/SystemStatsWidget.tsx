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

function badgeForBusy(busy: number): { label: string; cls: string } {
  if (busy >= 8) return { label: "HOT", cls: "bg-red-600 text-white" };
  if (busy >= 6) return { label: "BUSY", cls: "bg-orange-500 text-white" };
  if (busy >= 3) return { label: "ACTIVE", cls: "bg-yellow-400 text-black" };
  return { label: "IDLE", cls: "bg-green-600 text-white" };
}

export default function SystemStatsWidget() {
  const [data, setData] = useState<SystemStats | null>(null);
  const [err, setErr] = useState<string | null>(null);

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
  const badge = useMemo(() => badgeForBusy(busy), [busy]);

  if (err) {
    return (
      <div className="rounded-2xl border p-4 shadow-sm">
        <div className="text-sm font-semibold">System Stats</div>
        <div className="mt-2 text-sm text-red-600">Failed to load: {err}</div>
        <button className="mt-3 rounded-lg border px-3 py-1 text-sm" onClick={load}>
          Retry
        </button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-2xl border p-4 shadow-sm">
        <div className="text-sm font-semibold">System Stats</div>
        <div className="mt-2 text-sm text-gray-500">Loading…</div>
      </div>
    );
  }

  const upHours = (data.uptime_s / 3600).toFixed(1);

  return (
    <div className="rounded-2xl border p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">System Stats</div>
          <div className="text-xs text-gray-500">
            {data.hostname} · uptime {upHours}h · {new Date(data.timestamp * 1000).toLocaleTimeString()}
          </div>
        </div>
        <div className={`rounded-full px-3 py-1 text-xs font-semibold ${badge.cls}`}>
          {badge.label} · {busy.toFixed(1)}/10
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="CPU" value={`${data.cpu.percent_total.toFixed(1)}%`} sub={`cores ${data.cpu.cores_logical}`} />
        <Stat label="Mem" value={`${data.mem.percent.toFixed(1)}%`} sub={`${fmtBytes(data.mem.used)} used`} />
        <Stat label="Load" value={`${data.load.load1.toFixed(2)}`} sub={`${data.load.load5.toFixed(2)} / ${data.load.load15.toFixed(2)}`} />
        <Stat
          label="Net"
          value={data.net.total_rate ? `↓ ${fmtBps(data.net.total_rate.rx_Bps)}` : "—"}
          sub={data.net.total_rate ? `↑ ${fmtBps(data.net.total_rate.tx_Bps)}` : "warming up"}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="rounded-xl border p-3">
          <div className="text-xs font-semibold text-gray-600">Disks</div>
          <div className="mt-2 space-y-2">
            {Object.entries(data.disks).map(([mnt, d]) => (
              <div key={mnt}>
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono">{mnt}</span>
                  <span>{d.percent.toFixed(1)}%</span>
                </div>
                <div className="mt-1 h-2 w-full rounded bg-gray-200">
                  <div className="h-2 rounded bg-gray-700" style={{ width: `${Math.min(100, Math.max(0, d.percent))}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border p-3">
          <div className="text-xs font-semibold text-gray-600">API (last {data.api.window_s}s)</div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
            <Mini label="RPS" value={data.api.rps.toFixed(2)} />
            <Mini label="Inflight" value={String(data.api.inflight)} />
            <Mini label="p95" value={`${data.api.latency_ms_p95.toFixed(0)} ms`} />
            <Mini label="Err" value={`${(data.api.error_rate * 100).toFixed(1)}%`} />
          </div>

          <div className="mt-3 text-xs text-gray-600">Top paths</div>
          <div className="mt-1 space-y-1">
            {data.api.top_paths.slice(0, 3).map(([p, c]) => (
              <div key={p} className="flex items-center justify-between text-xs">
                <span className="truncate font-mono">{p}</span>
                <span className="ml-3">{c}</span>
              </div>
            ))}
            {data.api.top_paths.length === 0 && <div className="text-xs text-gray-400">No tracked requests (stats endpoint is excluded).</div>}
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat(props: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border p-3">
      <div className="text-xs font-semibold text-gray-600">{props.label}</div>
      <div className="mt-1 text-lg font-semibold">{props.value}</div>
      {props.sub && <div className="text-xs text-gray-500">{props.sub}</div>}
    </div>
  );
}

function Mini(props: { label: string; value: string }) {
  return (
    <div className="rounded-lg border px-2 py-1">
      <div className="text-[10px] font-semibold text-gray-600">{props.label}</div>
      <div className="text-sm font-semibold">{props.value}</div>
    </div>
  );
}

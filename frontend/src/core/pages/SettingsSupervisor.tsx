import { useEffect, useState } from "react";
import "./settings.css";
import "./home.css";

type SupervisorHostResources = {
  uptime_s?: number;
  load_1m?: number;
  load_5m?: number;
  load_15m?: number;
  cpu_percent_total?: number;
  cpu_cores_logical?: number;
  memory_total_bytes?: number;
  memory_available_bytes?: number;
  memory_percent?: number;
  root_disk_total_bytes?: number | null;
  root_disk_free_bytes?: number | null;
  root_disk_percent?: number | null;
};

type SupervisorHostProcess = {
  rss_bytes?: number | null;
  cpu_percent?: number | null;
  open_fds?: number | null;
  threads?: number | null;
};

type SupervisorRuntimeSummary = {
  host?: { host_id?: string; hostname?: string };
  resources?: SupervisorHostResources;
  process?: SupervisorHostProcess;
  managed_nodes?: Array<Record<string, unknown>>;
};

type SupervisorHealthSummary = {
  status?: string;
  host?: { host_id?: string; hostname?: string };
  resources?: SupervisorHostResources;
  managed_node_count?: number;
  healthy_node_count?: number;
  unhealthy_node_count?: number;
};

type SupervisorSummary = {
  ok: boolean;
  available?: boolean;
  error?: string;
  health?: SupervisorHealthSummary | null;
  runtime?: SupervisorRuntimeSummary | null;
  info?: Record<string, unknown> | null;
  nodes?: Array<Record<string, unknown>>;
  runtimes?: Array<Record<string, unknown>>;
  core_runtimes?: Array<Record<string, unknown>>;
};

type SystemStats = {
  hostname: string;
  uptime_s: number;
  cpu: { percent_total: number };
  mem: { percent: number };
  disks: Record<string, { percent: number }>;
  api?: {
    rps?: number;
    latency_ms_p95?: number;
    error_rate?: number;
    inflight?: number;
  };
};

type StackSummary = {
  connectivity: {
    network: { state: string };
    internet: { state: string };
  };
  samples: {
    internet_speed: {
      state: string;
      download_mbps?: number | null;
      upload_mbps?: number | null;
    };
    network_throughput?: {
      state: string;
      rx_Bps?: number | null;
      tx_Bps?: number | null;
    };
    network_metrics?: {
      state: string;
      bytes_sent?: number | null;
      bytes_recv?: number | null;
      errin?: number | null;
      errout?: number | null;
      dropin?: number | null;
      dropout?: number | null;
    };
  };
};

function displayState(value: unknown): string {
  const raw = String(value || "unknown").trim();
  if (!raw) return "Unknown";
  const normalized = raw.replace(/_/g, " ").toLowerCase();
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function statusTone(state: unknown): "ok" | "warn" | "bad" | "neutral" {
  const x = String(state || "unknown").toLowerCase();
  if (["healthy", "connected", "running", "active", "reachable", "ok", "idle", "online"].includes(x)) return "ok";
  if (["degraded", "unknown", "unavailable", "not_configured", "partial", "limited", "stale"].includes(x)) return "warn";
  if (["unhealthy", "disconnected", "unreachable", "error", "failed", "down", "offline", "stopped"].includes(x)) {
    return "bad";
  }
  return "neutral";
}

function formatPct(value: unknown): string {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return "-";
  return `${(parsed * 100).toFixed(1)}%`;
}

function formatMs(value: unknown): string {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return "-";
  return `${parsed.toFixed(0)} ms`;
}

function formatRps(value: unknown): string {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return "-";
  return parsed.toFixed(2);
}

function StatusLed({ tone }: { tone: "ok" | "warn" | "bad" | "neutral" }) {
  return <span className={`settings-led settings-led-${tone}`} />;
}

function fmtUptime(sec: number): string {
  const h = sec / 3600;
  if (h < 48) return `${h.toFixed(1)}h`;
  const d = Math.floor(h / 24);
  const rem = h - d * 24;
  return `${d}d ${rem.toFixed(0)}h`;
}

function pct(value: number): string {
  return `${Math.max(0, Math.min(100, value)).toFixed(1)}%`;
}

function formatNumber(value: unknown, fallback = "-"): string {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "number" && Number.isFinite(value)) return value.toLocaleString();
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString() : fallback;
}

function formatBytes(value: unknown): string {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = parsed;
  let idx = 0;
  while (size >= 1024 && idx < units.length - 1) {
    size /= 1024;
    idx += 1;
  }
  return `${size.toFixed(size >= 100 ? 0 : 1)} ${units[idx]}`;
}

function fmtBps(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "0 B/s";
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)} GB/s`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)} MB/s`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)} KB/s`;
  return `${value.toFixed(0)} B/s`;
}

function fmtBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "0 B";
  if (value >= 1_000_000_000_000) return `${(value / 1_000_000_000_000).toFixed(2)} TB`;
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)} GB`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)} MB`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)} KB`;
  return `${value.toFixed(0)} B`;
}

function speedValue(speed: StackSummary["samples"]["internet_speed"] | undefined): string {
  if (!speed) return "unknown";
  if (speed.state !== "ok") return speed.state;
  const down = typeof speed.download_mbps === "number" ? speed.download_mbps.toFixed(1) : "-";
  const up = typeof speed.upload_mbps === "number" ? speed.upload_mbps.toFixed(1) : "-";
  return `↓${down} ↑${up} Mbps`;
}

function throughputValue(throughput: StackSummary["samples"]["network_throughput"] | undefined): string {
  if (!throughput) return "unknown";
  if (throughput.state !== "ok") return throughput.state;
  const rx = typeof throughput.rx_Bps === "number" ? fmtBps(throughput.rx_Bps) : "-";
  const tx = typeof throughput.tx_Bps === "number" ? fmtBps(throughput.tx_Bps) : "-";
  return `↓${rx} ↑${tx}`;
}

function networkCountersValue(metrics: StackSummary["samples"]["network_metrics"] | undefined): string {
  if (!metrics) return "unknown";
  if (metrics.state !== "ok") return metrics.state;
  const rx = typeof metrics.bytes_recv === "number" ? fmtBytes(metrics.bytes_recv) : "-";
  const tx = typeof metrics.bytes_sent === "number" ? fmtBytes(metrics.bytes_sent) : "-";
  return `↓${rx} ↑${tx}`;
}

function networkErrorsValue(metrics: StackSummary["samples"]["network_metrics"] | undefined): string {
  if (!metrics) return "unknown";
  if (metrics.state !== "ok") return metrics.state;
  const errIn = Number(metrics.errin ?? 0);
  const errOut = Number(metrics.errout ?? 0);
  const dropIn = Number(metrics.dropin ?? 0);
  const dropOut = Number(metrics.dropout ?? 0);
  return `err ${errIn}/${errOut} drop ${dropIn}/${dropOut}`;
}

function renderMetadata(meta?: Record<string, unknown>): JSX.Element | null {
  if (!meta || Object.keys(meta).length === 0) return null;
  return <pre className="settings-pre">{JSON.stringify(meta, null, 2)}</pre>;
}

export default function SettingsSupervisor() {
  const [summary, setSummary] = useState<SupervisorSummary | null>(null);
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [stack, setStack] = useState<StackSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function loadSummary() {
    setErr(null);
    setLoading(true);
    try {
      const [supervisorRes, statsRes, stackRes] = await Promise.all([
        fetch("/api/system/supervisor/summary", { cache: "no-store" }),
        fetch("/api/system/stats/current", { cache: "no-store" }),
        fetch("/api/system/stack/summary", { cache: "no-store" }),
      ]);
      if (!supervisorRes.ok) throw new Error(`HTTP ${supervisorRes.status}`);
      setSummary((await supervisorRes.json()) as SupervisorSummary);
      if (statsRes.ok) setStats((await statsRes.json()) as SystemStats);
      if (stackRes.ok) setStack((await stackRes.json()) as StackSummary);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
      setSummary(null);
      setStats(null);
      setStack(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadSummary();
    const id = window.setInterval(() => {
      void loadSummary();
    }, 10000);
    return () => window.clearInterval(id);
  }, []);

  const coreRuntimesRaw = summary?.core_runtimes as unknown;
  const coreRuntimesFromItems =
    coreRuntimesRaw &&
    typeof coreRuntimesRaw === "object" &&
    Array.isArray((coreRuntimesRaw as { items?: unknown }).items)
      ? ((coreRuntimesRaw as { items?: unknown }).items as Array<Record<string, unknown>>)
      : [];
  const coreRuntimes = Array.isArray(coreRuntimesRaw) ? coreRuntimesRaw : coreRuntimesFromItems;
  const nodeRuntimes = Array.isArray(summary?.runtimes) ? summary?.runtimes : [];
  const coreServices = coreRuntimes.filter(
    (item) => String(item.runtime_kind || "").toLowerCase() !== "addon",
  );
  const addonRuntimes = coreRuntimes.filter(
    (item) => String(item.runtime_kind || "").toLowerCase() === "addon",
  );
  const addonContainers = addonRuntimes.flatMap((runtime) => {
    const containers = (runtime as { runtime_metadata?: { containers?: Array<Record<string, unknown>> } })
      .runtime_metadata?.containers;
    if (!Array.isArray(containers) || containers.length === 0) return [];
    return containers.map((container) => ({
      container,
      addonId: String(runtime.runtime_id || runtime.runtime_name || "addon"),
      addonName: String(runtime.runtime_name || runtime.runtime_id || "Addon"),
    }));
  });

  return (
    <div className="settings-page">
      <h1 className="settings-title">Settings / Supervisor</h1>
      <div className="settings-row">
        <div />
        <div className="settings-row-actions" />
      </div>

      {err && <div className="settings-error">Failed to load supervisor summary: {err}</div>}
      {summary?.error && <div className="settings-error">Supervisor error: {summary.error}</div>}

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>System Metrics</h2>
          <p>Matches the primary dashboard metrics for host health and connectivity.</p>
        </div>
        <div className="settings-card">
          {!stats ? (
            <div className="settings-help">Metrics unavailable.</div>
          ) : (
            <>
              <div className="settings-help">
                Host {stats.hostname} • uptime {fmtUptime(stats.uptime_s)}
              </div>
              <div className="settings-metrics-grid">
                <MetricBar label="CPU" percent={stats.cpu.percent_total} />
                <MetricBar label="Memory" percent={stats.mem.percent} />
                <MetricBar
                  label="Disk"
                  percent={
                    Object.values(stats.disks).length > 0
                      ? Math.max(...Object.values(stats.disks).map((x) => x.percent))
                      : 0
                  }
                />
                <MetricRow label="Network" value={displayState(stack?.connectivity.network.state || "unknown")} />
                <MetricRow label="Throughput" value={throughputValue(stack?.samples.network_throughput)} />
                <MetricRow label="Net I/O" value={networkCountersValue(stack?.samples.network_metrics)} />
                <MetricRow label="Net Errors" value={networkErrorsValue(stack?.samples.network_metrics)} />
                <MetricRow label="Internet" value={displayState(stack?.connectivity.internet.state || "unknown")} />
                <MetricRow label="Speed" value={speedValue(stack?.samples.internet_speed)} />
              </div>
            </>
          )}
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Core Services & Aux Runtimes</h2>
          <p>Core-owned services and aux containers registered with the local Supervisor.</p>
        </div>
        <div className="settings-card">
          {coreServices.length === 0 ? (
            <div className="settings-help">No Core services or aux runtimes registered yet.</div>
          ) : (
            <table className="settings-table">
              <thead>
                <tr>
                  <th />
                  <th>Name</th>
                  <th>ID</th>
                  <th>Kind</th>
                  <th>Mode</th>
                  <th>State</th>
                  <th>Health</th>
                  <th>Desired</th>
                  <th>RPS</th>
                  <th>P95</th>
                  <th>Err%</th>
                  <th>CPU</th>
                  <th>Mem</th>
                </tr>
              </thead>
              <tbody>
                {coreServices.map((runtime) => (
                  <tr key={String(runtime.runtime_id || runtime.runtime_name)}>
                    <td>
                      <StatusLed tone={statusTone(runtime.health_status || runtime.runtime_state)} />
                    </td>
                    <td>{String(runtime.runtime_name || runtime.runtime_id || "Unnamed")}</td>
                    <td className="settings-mono">{String(runtime.runtime_id || "-")}</td>
                    <td>{displayState(runtime.runtime_kind)}</td>
                    <td>{displayState(runtime.management_mode)}</td>
                    <td>{displayState(runtime.runtime_state)}</td>
                    <td>{displayState(runtime.health_status)}</td>
                    <td>{displayState(runtime.desired_state)}</td>
                    <td>{String(runtime.runtime_id) === "core-api" ? formatRps(stats?.api?.rps) : "-"}</td>
                    <td>{String(runtime.runtime_id) === "core-api" ? formatMs(stats?.api?.latency_ms_p95) : "-"}</td>
                    <td>{String(runtime.runtime_id) === "core-api" ? formatPct(stats?.api?.error_rate) : "-"}</td>
                    <td>{String(runtime.runtime_id) === "core-api" ? pct(stats?.cpu?.percent_total ?? 0) : "-"}</td>
                    <td>{String(runtime.runtime_id) === "core-api" ? pct(stats?.mem?.percent ?? 0) : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Node Runtimes</h2>
          <p>Supervisor-registered node runtime inventory and aux metadata.</p>
        </div>
        <div className="settings-card">
          {nodeRuntimes.length === 0 ? (
            <div className="settings-help">No node runtimes registered yet.</div>
          ) : (
            <table className="settings-table">
              <thead>
                <tr>
                  <th />
                  <th>Name</th>
                  <th>ID</th>
                  <th>Type</th>
                  <th>State</th>
                  <th>Health</th>
                  <th>Desired</th>
                  <th>Freshness</th>
                  <th>RPS</th>
                  <th>P95</th>
                  <th>Err%</th>
                  <th>CPU</th>
                  <th>Mem</th>
                </tr>
              </thead>
              <tbody>
                {nodeRuntimes.map((runtime) => (
                  <tr key={String(runtime.node_id || runtime.node_name)}>
                    <td>
                      <StatusLed tone={statusTone(runtime.freshness_state || runtime.health_status)} />
                    </td>
                    <td>{String(runtime.node_name || runtime.node_id || "Unnamed")}</td>
                    <td className="settings-mono">{String(runtime.node_id || "-")}</td>
                    <td>{String(runtime.node_type || "-")}</td>
                    <td>{displayState(runtime.runtime_state)}</td>
                    <td>{displayState(runtime.health_status)}</td>
                    <td>{displayState(runtime.desired_state)}</td>
                    <td>{displayState(runtime.freshness_state)}</td>
                    <td>{formatRps((runtime as { resource_usage?: { rps?: number } }).resource_usage?.rps)}</td>
                    <td>{formatMs((runtime as { resource_usage?: { latency_ms_p95?: number } }).resource_usage?.latency_ms_p95)}</td>
                    <td>{formatPct((runtime as { resource_usage?: { error_rate?: number } }).resource_usage?.error_rate)}</td>
                    <td>{formatPct((runtime as { resource_usage?: { cpu_percent?: number } }).resource_usage?.cpu_percent)}</td>
                    <td>{formatPct((runtime as { resource_usage?: { mem_percent?: number } }).resource_usage?.mem_percent)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Addons</h2>
          <p>Embedded addon runtimes registered to the local Supervisor.</p>
        </div>
        <div className="settings-card">
          {addonRuntimes.length === 0 ? (
            <div className="settings-help">No embedded addons registered yet.</div>
          ) : (
            <table className="settings-table">
              <thead>
                <tr>
                  <th />
                  <th>Name</th>
                  <th>ID</th>
                  <th>Mode</th>
                  <th>State</th>
                  <th>Health</th>
                  <th>Desired</th>
                  <th>RPS</th>
                  <th>P95</th>
                  <th>Err%</th>
                  <th>CPU</th>
                  <th>Mem</th>
                </tr>
              </thead>
              <tbody>
                {addonRuntimes.map((runtime) => (
                  <tr key={String(runtime.runtime_id || runtime.runtime_name)}>
                    <td>
                      <StatusLed tone={statusTone(runtime.health_status || runtime.runtime_state)} />
                    </td>
                    <td>{String(runtime.runtime_name || runtime.runtime_id || "Addon")}</td>
                    <td className="settings-mono">{String(runtime.runtime_id || "-")}</td>
                    <td>{displayState(runtime.management_mode)}</td>
                    <td>{displayState(runtime.runtime_state)}</td>
                    <td>{displayState(runtime.health_status)}</td>
                    <td>{displayState(runtime.desired_state)}</td>
                    <td>{formatRps((runtime as { resource_usage?: { rps?: number } }).resource_usage?.rps)}</td>
                    <td>{formatMs((runtime as { resource_usage?: { latency_ms_p95?: number } }).resource_usage?.latency_ms_p95)}</td>
                    <td>{formatPct((runtime as { resource_usage?: { error_rate?: number } }).resource_usage?.error_rate)}</td>
                    <td>{formatPct((runtime as { resource_usage?: { cpu_percent?: number } }).resource_usage?.cpu_percent)}</td>
                    <td>{formatPct((runtime as { resource_usage?: { mem_percent?: number } }).resource_usage?.mem_percent)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Addon Containers</h2>
          <p>Embedded addon containers surfaced as standalone runtime entities.</p>
        </div>
        <div className="settings-card">
          {addonContainers.length === 0 ? (
            <div className="settings-help">No addon containers reported yet.</div>
          ) : (
            <table className="settings-table">
              <thead>
                <tr>
                  <th />
                  <th>Container</th>
                  <th>Status</th>
                  <th>Healthy</th>
                  <th>Provider</th>
                  <th>Reason</th>
                  <th>Addon</th>
                </tr>
              </thead>
              <tbody>
                {addonContainers.map((entry) => (
                  <tr key={`${entry.addonId}:${String(entry.container?.name || entry.container?.container_name || "container")}`}>
                    <td>
                      <StatusLed tone={statusTone(entry.container?.status || entry.container?.state || entry.container?.healthy)} />
                    </td>
                    <td className="settings-mono">
                      {String(entry.container?.name || entry.container?.container_name || "container")}
                    </td>
                    <td>{displayState(entry.container?.status || entry.container?.state)}</td>
                    <td>{entry.container?.healthy === undefined ? "-" : displayState(entry.container?.healthy ? "healthy" : "unhealthy")}</td>
                    <td>{String(entry.container?.provider || "-")}</td>
                    <td>{String(entry.container?.degraded_reason || entry.container?.last_error || "-")}</td>
                    <td>{entry.addonName}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="home-metric-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MetricBar({ label, percent }: { label: string; percent: number }) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div className="home-metric-bar">
      <div className="home-metric-bar-top">
        <span>{label}</span>
        <strong>{pct(clamped)}</strong>
      </div>
      <div className="home-metric-bar-track">
        <div className="home-metric-bar-fill" style={{ width: `${clamped}%` }} />
      </div>
    </div>
  );
}

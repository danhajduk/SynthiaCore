import { Fragment, useEffect, useState } from "react";
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

type NodeServiceRow = {
  node_id: string;
  node_name: string;
  service_id: string;
  service_name: string;
  service_state: string;
  desired_state?: string;
  health_status?: string;
  cpu_percent?: number;
  mem_percent?: number;
  pid?: number;
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

function formatPctValue(value: unknown): string {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return "-";
  return `${parsed.toFixed(1)}%`;
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
  const [actionBusy, setActionBusy] = useState<Record<string, string | null>>({});
  const [expandedNodes, setExpandedNodes] = useState<Record<string, boolean>>({});

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
  const nodeServices: NodeServiceRow[] = nodeRuntimes.flatMap((runtime) => {
    const meta = (runtime as { runtime_metadata?: Record<string, unknown> }).runtime_metadata;
    const services = meta && typeof meta === "object" ? (meta as { services?: unknown }).services : undefined;
    if (!services) return [];
    const nodeId = String(runtime.node_id || "");
    const nodeName = String(runtime.node_name || runtime.node_id || "Node");
    if (Array.isArray(services)) {
      const mapped = services
        .map((item) => {
          if (!item || typeof item !== "object") return null;
          const svc = item as Record<string, unknown>;
          const serviceId = String(svc.service_id || svc.id || svc.name || "");
          if (!serviceId) return null;
          const normalized: NodeServiceRow = {
            node_id: nodeId,
            node_name: nodeName,
            service_id: serviceId,
            service_name: String(svc.service_name || svc.name || serviceId),
            service_state: String(svc.service_state || svc.state || svc.status || "unknown"),
            desired_state: svc.desired_state ? String(svc.desired_state) : undefined,
            health_status: svc.health_status ? String(svc.health_status) : undefined,
            cpu_percent: typeof svc.cpu_percent === "number" ? svc.cpu_percent : undefined,
            mem_percent: typeof svc.mem_percent === "number" ? svc.mem_percent : undefined,
            pid: typeof svc.pid === "number" ? svc.pid : undefined,
          };
          return normalized.service_id === "node" ? null : normalized;
        })
        .filter((item): item is NodeServiceRow => Boolean(item));
      return mapped;
    }
    if (typeof services === "object") {
      const mapped = Object.entries(services as Record<string, unknown>)
        .map(([key, value]) => {
          if (String(key) === "node") return null;
          if (value && typeof value === "object") {
            const svc = value as Record<string, unknown>;
            const normalized: NodeServiceRow = {
              node_id: nodeId,
              node_name: nodeName,
              service_id: String(key),
              service_name: String(svc.service_name || svc.name || key),
              service_state: String(svc.service_state || svc.state || svc.status || "unknown"),
              desired_state: svc.desired_state ? String(svc.desired_state) : undefined,
              health_status: svc.health_status ? String(svc.health_status) : undefined,
              cpu_percent: typeof svc.cpu_percent === "number" ? svc.cpu_percent : undefined,
              mem_percent: typeof svc.mem_percent === "number" ? svc.mem_percent : undefined,
              pid: typeof svc.pid === "number" ? svc.pid : undefined,
            };
            return normalized;
          }
          const fallback: NodeServiceRow = {
            node_id: nodeId,
            node_name: nodeName,
            service_id: String(key),
            service_name: String(key),
            service_state: String(value || "unknown"),
          };
          return fallback;
        })
        .filter((item): item is NodeServiceRow => Boolean(item));
      return mapped;
    }
    return [];
  });

  const nodeServicesByNode = nodeServices.reduce<Record<string, NodeServiceRow[]>>((acc, service) => {
    const key = String(service.node_id || "");
    if (!key) return acc;
    if (!acc[key]) acc[key] = [];
    acc[key].push(service);
    return acc;
  }, {});
  const hasServicePid = nodeServices.some((service) => typeof service.pid === "number");

  async function runNodeRuntimeAction(nodeId: string, action: "start" | "stop" | "restart") {
    if (!nodeId) return;
    const services = nodeServicesByNode[nodeId] || [];
    if (services.length === 0) return;
    setErr(null);
    setActionBusy((prev) => ({ ...prev, [nodeId]: action }));
    try {
      const results = await Promise.all(
        services.map((service) =>
          fetch(
            `/api/supervisor/runtimes/${encodeURIComponent(nodeId)}/services/${encodeURIComponent(service.service_id)}/${action}`,
            { method: "POST" },
          ),
        ),
      );
      const failed = results.find((res) => !res.ok);
      if (failed) throw new Error(`HTTP ${failed.status}`);
      await loadSummary();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setActionBusy((prev) => ({ ...prev, [nodeId]: null }));
    }
  }

  function toggleNodeDetails(nodeId: string) {
    setExpandedNodes((prev) => ({ ...prev, [nodeId]: !prev[nodeId] }));
  }

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
        </div>
        {nodeRuntimes.length === 0 ? (
          <div className="settings-card">
            <div className="settings-help">No node runtimes registered yet.</div>
          </div>
        ) : (
          <div className="settings-node-list">
            {nodeRuntimes.map((runtime) => {
              const nodeId = String(runtime.node_id || "");
              const services = nodeServicesByNode[nodeId] || [];
              const servicesCpu = services.reduce(
                (sum, service) => sum + (typeof service.cpu_percent === "number" ? service.cpu_percent : 0),
                0,
              );
              const servicesMem = services.reduce(
                (sum, service) => sum + (typeof service.mem_percent === "number" ? service.mem_percent : 0),
                0,
              );
              const runtimeUsage = runtime as { resource_usage?: { cpu_percent?: number; mem_percent?: number } };
              const nodeCpu = services.length > 0 ? servicesCpu : runtimeUsage.resource_usage?.cpu_percent;
              const nodeMem = services.length > 0 ? servicesMem : runtimeUsage.resource_usage?.mem_percent;
              return (
                <div key={`runtime:${nodeId || runtime.node_name}`} className="settings-card settings-node-card">
                  <div className="settings-node-header">
                    <div className="settings-node-title">
                      <StatusLed tone={statusTone(runtime.freshness_state || runtime.health_status)} />
                      <div>
                        <strong>{String(runtime.node_name || runtime.node_id || "Unnamed")}</strong>
                        <div className="settings-muted settings-mono">{nodeId || "-"}</div>
                      </div>
                    </div>
                    <div className="settings-node-actions">
                      <button
                        className="settings-btn"
                        type="button"
                        onClick={() => void runNodeRuntimeAction(nodeId, "start")}
                        disabled={actionBusy[nodeId] !== null && actionBusy[nodeId] !== undefined}
                      >
                        Start
                      </button>
                      <button
                        className="settings-btn"
                        type="button"
                        onClick={() => void runNodeRuntimeAction(nodeId, "stop")}
                        disabled={actionBusy[nodeId] !== null && actionBusy[nodeId] !== undefined}
                      >
                        Stop
                      </button>
                      <button
                        className="settings-btn"
                        type="button"
                        onClick={() => void runNodeRuntimeAction(nodeId, "restart")}
                        disabled={actionBusy[nodeId] !== null && actionBusy[nodeId] !== undefined}
                      >
                        Restart
                      </button>
                      <button className="settings-btn" type="button" onClick={() => toggleNodeDetails(nodeId)}>
                        {expandedNodes[nodeId] ? "Hide Services" : "Show Services"}
                      </button>
                    </div>
                  </div>
                  <div className="settings-node-grid">
                    <div>
                      <div className="settings-node-label">Runtime</div>
                      <strong>{String((runtime as { runtime_kind?: string }).runtime_kind || runtime.node_type || "-")}</strong>
                    </div>
                    <div>
                      <div className="settings-node-label">Desired State</div>
                      <strong>{displayState(runtime.desired_state)}</strong>
                    </div>
                    <div>
                      <div className="settings-node-label">Runtime State</div>
                      <strong>{displayState(runtime.runtime_state)}</strong>
                    </div>
                    <div>
                      <div className="settings-node-label">Health</div>
                      <strong>{displayState(runtime.health_status)}</strong>
                    </div>
                    {(runtime as { hostname?: string }).hostname && (
                      <div>
                        <div className="settings-node-label">Host</div>
                        <strong>{String((runtime as { hostname?: string }).hostname)}</strong>
                      </div>
                    )}
                    {(runtime as { host_id?: string }).host_id && (
                      <div>
                        <div className="settings-node-label">Host ID</div>
                        <strong>{String((runtime as { host_id?: string }).host_id)}</strong>
                      </div>
                    )}
                    <div>
                      <div className="settings-node-label">CPU</div>
                      <strong>{formatPctValue(nodeCpu)}</strong>
                    </div>
                    <div>
                      <div className="settings-node-label">Mem</div>
                      <strong>{formatPctValue(nodeMem)}</strong>
                    </div>
                  </div>
                  <div className="settings-node-details">
                    <div className="settings-subtable-label">Runtime Details</div>
                    <div className="settings-kv-grid">
                      {(runtime as { active_version?: string }).active_version && (
                        <div className="settings-kv-item">
                          <div>Active Version</div>
                          <strong>{String((runtime as { active_version?: string }).active_version)}</strong>
                        </div>
                      )}
                      {(runtime as { last_action?: string }).last_action && (
                        <div className="settings-kv-item">
                          <div>Last Action</div>
                          <strong>{String((runtime as { last_action?: string }).last_action)}</strong>
                        </div>
                      )}
                      {(runtime as { last_action_at?: string }).last_action_at && (
                        <div className="settings-kv-item">
                          <div>Last Action At</div>
                          <strong>{String((runtime as { last_action_at?: string }).last_action_at)}</strong>
                        </div>
                      )}
                    </div>
                  </div>
                  {expandedNodes[nodeId] && (
                    <div className="settings-subtable-wrap">
                      <div className="settings-subtable-label">Services</div>
                      {services.length === 0 ? (
                        <div className="settings-help">No node services reported yet.</div>
                      ) : (
                        <table className="settings-subtable">
                          <thead>
                            <tr>
                              <th />
                              <th>Name</th>
                              <th>ID</th>
                              <th>State</th>
                              <th>Health</th>
                              <th>CPU</th>
                              <th>Mem</th>
                              {hasServicePid && <th>PID</th>}
                            </tr>
                          </thead>
                          <tbody>
                            {services.map((service) => (
                              <tr key={`service:${nodeId}:${service.service_id}`}>
                                <td>
                                  <StatusLed tone={statusTone(service.health_status || service.service_state)} />
                                </td>
                                <td>{service.service_name}</td>
                                <td className="settings-mono">{service.service_id}</td>
                                <td>{displayState(service.service_state)}</td>
                                <td>{displayState(service.health_status || service.service_state)}</td>
                                <td>{service.cpu_percent == null ? "" : formatPctValue(service.cpu_percent)}</td>
                                <td>{service.mem_percent == null ? "" : formatPctValue(service.mem_percent)}</td>
                                {hasServicePid && <td>{service.pid ?? ""}</td>}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Addons</h2>
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
                    <td>{formatPctValue((runtime as { resource_usage?: { cpu_percent?: number } }).resource_usage?.cpu_percent)}</td>
                    <td>{formatPctValue((runtime as { resource_usage?: { mem_percent?: number } }).resource_usage?.mem_percent)}</td>
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
                  <th>RPS</th>
                  <th>P95</th>
                  <th>Err%</th>
                  <th>CPU</th>
                  <th>Mem</th>
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
                    <td>{formatRps(entry.container?.rps)}</td>
                    <td>{formatMs(entry.container?.latency_ms_p95)}</td>
                    <td>{formatPct(entry.container?.error_rate)}</td>
                    <td>{formatPctValue(entry.container?.cpu_percent)}</td>
                    <td>{formatPctValue(entry.container?.mem_percent)}</td>
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

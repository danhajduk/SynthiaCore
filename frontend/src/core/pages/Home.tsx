import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  BrainCircuit,
  Clock3,
  Cog,
  Cpu,
  Globe,
  Network,
  Puzzle,
  ShieldCheck,
  Waypoints,
  type LucideIcon,
} from "lucide-react";

import { useAdminSession } from "../auth/AdminSessionContext";
import "./home.css";

type AddonSummary = {
  id: string;
  name?: string;
  version?: string;
  enabled?: boolean;
  health_status?: string;
  discovery_source?: string;
  updated_at?: string | null;
};

type SystemStats = {
  timestamp: number;
  hostname: string;
  uptime_s: number;
  cpu: { percent_total: number };
  mem: { percent: number };
  disks: Record<string, { percent: number }>;
  busy_rating: number;
};

type RepoStatus = {
  ok: boolean;
  update_available?: boolean;
  status?: string;
};

type StackSummary = {
  status: {
    overall: "ok" | "degraded" | "attention" | "unknown";
    reasons: string[];
    updated_at: string;
  };
  subsystems: {
    core: { state: string };
    supervisor: { state: string };
    ai: { state: string; trusted_nodes?: number; total_nodes?: number };
    mqtt: { state: string; last_message_at?: string | null };
    scheduler: { state: string; active_leases: number; queued_jobs: number };
    workers: { state: string; active_count: number };
    addons: { state: string; installed_count: number; unhealthy_count: number };
  };
  connectivity: {
    network: { state: string };
    internet: { state: string };
  };
  samples: {
    internet_speed: {
      state: string;
      source?: string;
      download_mbps?: number | null;
      upload_mbps?: number | null;
      latency_ms?: number | null;
      sampled_at?: string | null;
      age_s?: number;
    };
    network_throughput?: {
      state: string;
      rx_Bps?: number | null;
      tx_Bps?: number | null;
      sampled_at?: string | null;
    };
    network_metrics?: {
      state: string;
      bytes_sent?: number | null;
      bytes_recv?: number | null;
      packets_sent?: number | null;
      packets_recv?: number | null;
      errin?: number | null;
      errout?: number | null;
      dropin?: number | null;
      dropout?: number | null;
      sampled_at?: string | null;
    };
  };
};

type NodeRegistrationSummary = {
  node_id: string;
  node_name?: string;
  node_type?: string;
  trust_status?: string;
  registry_state?: string;
};

export const HOME_STATUS_TILE_TITLES = [
  "Core",
  "Supervisor",
  "MQTT",
  "Scheduler",
  "Workers",
  "Addons",
  "Network",
  "Internet",
  "AI Node",
] as const;

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

function summaryTone(overall: string): "ok" | "warn" | "danger" {
  if (overall === "attention") return "danger";
  if (overall === "degraded" || overall === "unknown") return "warn";
  return "ok";
}

function summaryLabel(overall: string): string {
  if (overall === "attention") return "ATTENTION";
  if (overall === "degraded") return "DEGRADED";
  if (overall === "unknown") return "UNKNOWN";
  return "READY";
}

function pillTone(state: string): "ok" | "warn" | "bad" | "neutral" {
  const x = String(state || "unknown").toLowerCase();
  if (["healthy", "connected", "running", "active", "reachable", "ok", "idle"].includes(x)) return "ok";
  if (["degraded", "unknown", "unavailable", "not_configured", "partial", "limited"].includes(x)) return "warn";
  if (["unhealthy", "disconnected", "unreachable", "error", "failed", "down", "offline", "stopped"].includes(x)) {
    return "bad";
  }
  return "neutral";
}

function speedValue(speed: StackSummary["samples"]["internet_speed"] | undefined): string {
  if (!speed) return "unknown";
  if (speed.state !== "ok") return speed.state;
  const down = typeof speed.download_mbps === "number" ? speed.download_mbps.toFixed(1) : "-";
  const up = typeof speed.upload_mbps === "number" ? speed.upload_mbps.toFixed(1) : "-";
  return `↓${down} ↑${up} Mbps`;
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

function schedulerLoadValue(stats: SystemStats | null): string {
  const busy = Number(stats?.busy_rating ?? 0);
  return `${Math.max(0, busy).toFixed(1)}/10`;
}

function schedulerLoadTone(stats: SystemStats | null): "ok" | "warn" | "bad" | "neutral" {
  if (!stats) return "neutral";
  const busy = Math.max(0, Number(stats.busy_rating ?? 0));
  if (busy >= 8) return "bad";
  if (busy >= 6) return "warn";
  return "ok";
}

function displayState(value: string): string {
  const raw = String(value || "unknown").trim();
  if (!raw) return "Unknown";
  const normalized = raw.replace(/_/g, " ").toLowerCase();
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function addonHealthState(item: AddonSummary, stack: StackSummary | null): string {
  const raw = String(item.health_status || "").trim().toLowerCase();
  if (raw && raw !== "unknown") return raw;
  if (item.id === "mqtt") return String(stack?.subsystems.mqtt.state || "unknown").toLowerCase();
  return raw || "unknown";
}

export default function Home() {
  const { authenticated, login, logout, ready } = useAdminSession();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [addons, setAddons] = useState<AddonSummary[]>([]);
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [repoStatus, setRepoStatus] = useState<RepoStatus | null>(null);
  const [stack, setStack] = useState<StackSummary | null>(null);
  const [nodes, setNodes] = useState<NodeRegistrationSummary[]>([]);
  const [dataErr, setDataErr] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [showReasons, setShowReasons] = useState(false);

  async function loadDashboardData() {
    try {
      const [addonsRes, statsRes, repoRes, stackRes, nodesRes] = await Promise.all([
        fetch("/api/addons", { cache: "no-store" }),
        fetch("/api/system/stats/current", { cache: "no-store" }),
        fetch("/api/system/repo/status", { cache: "no-store" }),
        fetch("/api/system/stack/summary", { cache: "no-store" }),
        fetch("/api/system/nodes/registry", { cache: "no-store", credentials: "include" }),
      ]);
      if (addonsRes.ok) setAddons((await addonsRes.json()) as AddonSummary[]);
      if (statsRes.ok) setStats((await statsRes.json()) as SystemStats);
      if (repoRes.ok) setRepoStatus((await repoRes.json()) as RepoStatus);
      if (stackRes.ok) setStack((await stackRes.json()) as StackSummary);
      if (nodesRes.ok) {
        const payload = (await nodesRes.json()) as { items?: NodeRegistrationSummary[] };
        setNodes(Array.isArray(payload.items) ? payload.items : []);
      } else {
        setNodes([]);
      }
      setDataErr(null);
      setLastUpdated(
        new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        }),
      );
    } catch (e: unknown) {
      setDataErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void loadDashboardData();
    const id = setInterval(() => {
      void loadDashboardData();
    }, 10000);
    return () => clearInterval(id);
  }, []);

  async function submitLogin() {
    if (!username.trim() || !password) {
      setErr("username_and_password_required");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const result = await login(username.trim(), password);
      if (!result.ok) {
        setErr(result.error || "login_failed");
        return;
      }
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  async function submitLogout() {
    setBusy(true);
    setErr(null);
    try {
      await logout();
    } finally {
      setBusy(false);
    }
  }

  const installedAddons = useMemo(
    () => addons.filter((item) => item.enabled !== false).sort((a, b) => a.id.localeCompare(b.id)),
    [addons],
  );
  const installedNodes = useMemo(
    () =>
      nodes
        .filter((item) => String(item.registry_state || item.trust_status || "").toLowerCase() === "trusted")
        .sort((a, b) => String(a.node_id || "").localeCompare(String(b.node_id || ""))),
    [nodes],
  );
  const nodeSummary = useMemo(() => {
    let trusted = 0;
    let pending = 0;
    let error = 0;
    for (const item of nodes) {
      const state = String(item.registry_state || item.trust_status || "").toLowerCase();
      if (state === "trusted") {
        trusted += 1;
      } else if (state === "revoked" || state === "rejected") {
        error += 1;
      } else {
        pending += 1;
      }
    }
    return { trusted, pending, error };
  }, [nodes]);

  const status = useMemo(() => {
    if (!stack) {
      return {
        label: "UNKNOWN",
        detail: "Stack summary unavailable",
        tone: "warn" as const,
        reasons: ["Stack summary unavailable"],
      };
    }
    const reasons = Array.isArray(stack.status.reasons) ? stack.status.reasons : [];
    return {
      label: summaryLabel(stack.status.overall),
      detail: reasons.length > 0 ? reasons[0] : "Core services healthy",
      tone: summaryTone(stack.status.overall),
      reasons,
    };
  }, [stack]);

  return (
    <div className="home-page">
      <section className="home-head">
        <div>
          <h1 className="home-title">Home Dashboard</h1>
          <p className="home-subtitle">
            Operational overview for core services, addons, workers, connectivity, and recent platform activity.
          </p>
        </div>
        <div className="home-head-meta">
          <span className="home-pill">{repoStatus?.update_available ? "Update available" : "Core up to date"}</span>
          <span className="home-pill home-pill-muted">
            {stats ? `${stats.hostname} • uptime ${fmtUptime(stats.uptime_s)}` : "Host unavailable"}
          </span>
          {lastUpdated && <span className="home-pill home-pill-muted">updated {lastUpdated}</span>}
        </div>
      </section>

      <section className="home-session-strip">
        {!ready ? (
          <div className="home-session-card">Checking session...</div>
        ) : authenticated ? (
          <div className="home-session-card">
            <span>Admin session active</span>
            <button className="home-btn" onClick={submitLogout} disabled={busy}>
              {busy ? "Signing out..." : "Sign out"}
            </button>
          </div>
        ) : (
          <div className="home-session-card home-session-login">
            <span>Guest mode active</span>
            <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="admin" className="home-input" />
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              type="password"
              className="home-input"
            />
            <button className="home-btn" onClick={submitLogin} disabled={busy || !username.trim() || !password}>
              {busy ? "Signing in..." : "Sign in"}
            </button>
          </div>
        )}
        {err && <div className="home-auth-err">{err}</div>}
      </section>

      <section className={`home-status-card tone-${status.tone}`}>
        <div className="home-status-summary">
          <div className="home-status-label">{status.label}</div>
          <div className="home-status-detail">{status.detail}</div>
          {status.reasons.length > 1 && (
            <button className="home-reason-btn" onClick={() => setShowReasons((prev) => !prev)}>
              {showReasons ? "Hide details" : `Show details (${status.reasons.length})`}
            </button>
          )}
          {showReasons && status.reasons.length > 0 && (
            <ul className="home-reason-list">
              {status.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
        </div>
        <div className="home-status-tiles-wrap">
          <section className="home-status-row">
            <StatusMini
              title="Core"
              tone={pillTone(stack?.subsystems.core.state || "unknown")}
              icon={Cpu}
            />
            <StatusMini
              title="Supervisor"
              tone={pillTone(stack?.subsystems.supervisor.state || "unknown")}
              icon={ShieldCheck}
            />
            <StatusMini
              title="Scheduler"
              tone={pillTone(stack?.subsystems.scheduler.state || "unknown")}
              icon={Clock3}
            />
            <StatusMini
              title="MQTT"
              tone={pillTone(stack?.subsystems.mqtt.state || "unknown")}
              icon={Waypoints}
            />
            <StatusMini
              title="AI Node"
              tone={pillTone(stack?.subsystems.ai?.state || "unknown")}
              icon={BrainCircuit}
            />
            <StatusMini
              title="Workers"
              tone={pillTone(stack?.subsystems.workers.state || "unknown")}
              icon={Cog}
            />
            <StatusMini
              title="Addons"
              tone={pillTone(stack?.subsystems.addons.state || "unknown")}
              icon={Puzzle}
            />
            <StatusMini
              title="Network"
              tone={pillTone(stack?.connectivity.network.state || "unknown")}
              icon={Network}
            />
            <StatusMini
              title="Internet"
              tone={pillTone(stack?.connectivity.internet.state || "unknown")}
              icon={Globe}
            />
          </section>
        </div>
      </section>

      {dataErr && <div className="home-data-err">Dashboard data load failed: {dataErr}</div>}

      <section className="home-grid">
        <article className="home-panel">
          <div className="home-panel-head">
            <h2>Installed Addons</h2>
            <Link to="/addons" className="home-link">Open Addons</Link>
          </div>
          {installedAddons.length === 0 ? (
            <div className="home-empty">No installed addons yet.</div>
          ) : (
            <div className="home-addon-list">
              {installedAddons.slice(0, 10).map((item) => {
                const healthState = addonHealthState(item, stack);
                return (
                <div key={item.id} className="home-addon-item">
                  <div>
                    <div className="home-addon-name">{item.name || item.id}</div>
                    <div className="home-addon-meta">{item.id} • {item.version || "unknown"}</div>
                  </div>
                  <span className={`home-chip state-${healthState}`}>
                    {displayState(healthState)}
                  </span>
                </div>
                );
              })}
            </div>
          )}
        </article>

        <article className="home-panel">
          <div className="home-panel-head">
            <h2>Nodes Summary</h2>
            <Link to="/addons" className="home-link">Open Nodes</Link>
          </div>
          <div className="home-metrics">
            <MetricRow label="Trusted" value={String(nodeSummary.trusted)} />
            <MetricRow label="Pending" value={String(nodeSummary.pending)} />
            <MetricRow label="Error" value={String(nodeSummary.error)} />
          </div>
          {nodes.length === 0 && <div className="home-empty">No registered nodes yet.</div>}
        </article>

        <article className="home-panel">
          <div className="home-panel-head">
            <h2>System Metrics</h2>
          </div>
          {!stats ? (
            <div className="home-empty">Metrics unavailable.</div>
          ) : (
            <div className="home-metrics">
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
          )}
        </article>
      </section>
    </div>
  );
}

export function StatusMini({
  title,
  icon: Icon,
  tone = "neutral",
}: {
  title: string;
  icon?: LucideIcon;
  tone?: "ok" | "warn" | "bad" | "neutral";
}) {
  return (
    <div className={`home-mini ${tone}`}>
      {Icon && <Icon className="home-mini-icon" />}
      <div className="home-mini-title">{title}</div>
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

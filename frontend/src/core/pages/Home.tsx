import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

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

type EventItem = {
  id: string;
  event_type: string;
  timestamp: string;
  source: string;
  payload?: Record<string, unknown>;
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

function relative(ts: string): string {
  const t = Date.parse(ts);
  if (!Number.isFinite(t)) return ts;
  const deltaS = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (deltaS < 60) return `${deltaS}s ago`;
  if (deltaS < 3600) return `${Math.floor(deltaS / 60)}m ago`;
  if (deltaS < 86400) return `${Math.floor(deltaS / 3600)}h ago`;
  return `${Math.floor(deltaS / 86400)}d ago`;
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
  if (["degraded", "unknown", "unavailable", "not_configured"].includes(x)) return "warn";
  if (["unhealthy", "disconnected", "unreachable", "error", "failed", "down"].includes(x)) return "bad";
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

function displayState(value: string): string {
  const raw = String(value || "unknown").trim();
  if (!raw) return "Unknown";
  const normalized = raw.replace(/_/g, " ").toLowerCase();
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export default function Home() {
  const { authenticated, login, logout, ready } = useAdminSession();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [addons, setAddons] = useState<AddonSummary[]>([]);
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [repoStatus, setRepoStatus] = useState<RepoStatus | null>(null);
  const [stack, setStack] = useState<StackSummary | null>(null);
  const [dataErr, setDataErr] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [showReasons, setShowReasons] = useState(false);

  async function loadDashboardData() {
    try {
      const [addonsRes, statsRes, eventsRes, repoRes, stackRes] = await Promise.all([
        fetch("/api/addons", { cache: "no-store" }),
        fetch("/api/system/stats/current", { cache: "no-store" }),
        fetch("/api/system/events?limit=8", { cache: "no-store" }),
        fetch("/api/system/repo/status", { cache: "no-store" }),
        fetch("/api/system/stack/summary", { cache: "no-store" }),
      ]);
      if (addonsRes.ok) setAddons((await addonsRes.json()) as AddonSummary[]);
      if (statsRes.ok) setStats((await statsRes.json()) as SystemStats);
      if (eventsRes.ok) {
        const payload = (await eventsRes.json()) as { items?: EventItem[] };
        setEvents(Array.isArray(payload.items) ? payload.items : []);
      }
      if (repoRes.ok) setRepoStatus((await repoRes.json()) as RepoStatus);
      if (stackRes.ok) setStack((await stackRes.json()) as StackSummary);
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
        <div>
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
        <div className="home-subsystems">
          <span className={`home-subsystem ${pillTone(stack?.subsystems.core.state || "unknown")}`}>Core</span>
          <span className={`home-subsystem ${pillTone(stack?.subsystems.supervisor.state || "unknown")}`}>Supervisor</span>
          <span className={`home-subsystem ${pillTone(stack?.subsystems.mqtt.state || "unknown")}`}>MQTT</span>
          <span className={`home-subsystem ${pillTone(stack?.subsystems.scheduler.state || "unknown")}`}>Scheduler</span>
          <span className={`home-subsystem ${pillTone(stack?.subsystems.workers.state || "unknown")}`}>Workers</span>
          <span className={`home-subsystem ${pillTone(stack?.subsystems.addons.state || "unknown")}`}>Addons</span>
          <span className={`home-subsystem ${pillTone(stack?.connectivity.network.state || "unknown")}`}>Network</span>
          <span className={`home-subsystem ${pillTone(stack?.connectivity.internet.state || "unknown")}`}>Internet</span>
        </div>
      </section>

      <section className="home-status-row">
        <StatusMini title="Core" value={stack?.subsystems.core.state || "unknown"} />
        <StatusMini title="Supervisor" value={stack?.subsystems.supervisor.state || "unknown"} />
        <StatusMini
          title="Scheduler"
          value={stack?.subsystems.scheduler.state || "unknown"}
          sub={stack ? `${stack.subsystems.scheduler.queued_jobs} queued` : undefined}
        />
        <StatusMini title="MQTT" value={stack?.subsystems.mqtt.state || "unknown"} />
        <StatusMini
          title="Workers"
          value={String(stack?.subsystems.workers.active_count ?? 0)}
          sub={stack?.subsystems.workers.state || "unknown"}
        />
        <StatusMini
          title="Addons"
          value={String(stack?.subsystems.addons.installed_count ?? installedAddons.length)}
          sub={`${stack?.subsystems.addons.unhealthy_count ?? 0} unhealthy`}
        />
        <StatusMini title="Network" value={stack?.connectivity.network.state || "unknown"} />
        <StatusMini title="Internet" value={stack?.connectivity.internet.state || "unknown"} />
        <StatusMini
          title="Speed"
          value={speedValue(stack?.samples.internet_speed)}
          sub={
            stack?.samples.internet_speed?.sampled_at
              ? `${stack.samples.internet_speed.source === "passive_estimate" ? "estimated" : "sample"} ${relative(stack.samples.internet_speed.sampled_at)}`
              : undefined
          }
        />
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
              {installedAddons.slice(0, 10).map((item) => (
                <div key={item.id} className="home-addon-item">
                  <div>
                    <div className="home-addon-name">{item.name || item.id}</div>
                    <div className="home-addon-meta">{item.id} • {item.version || "unknown"}</div>
                  </div>
                  <span className={`home-chip state-${String(item.health_status || "unknown").toLowerCase()}`}>
                    {item.health_status || "unknown"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </article>

        <article className="home-panel">
          <div className="home-panel-head">
            <h2>Recent Activity</h2>
          </div>
          {events.length === 0 ? (
            <div className="home-empty">No recent event entries available.</div>
          ) : (
            <div className="home-activity-list">
              {events.map((item) => (
                <div key={item.id} className="home-activity-item">
                  <div className="home-activity-top">
                    <span className="home-chip">{item.event_type}</span>
                    <span className="home-activity-time">{relative(item.timestamp)}</span>
                  </div>
                  <div className="home-activity-source">{item.source}</div>
                </div>
              ))}
            </div>
          )}
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

function StatusMini({ title, value, sub }: { title: string; value: string; sub?: string }) {
  return (
    <div className="home-mini">
      <div className="home-mini-title">{title}</div>
      <div className="home-mini-value">{displayState(value)}</div>
      {sub && <div className="home-mini-sub">{displayState(sub)}</div>}
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

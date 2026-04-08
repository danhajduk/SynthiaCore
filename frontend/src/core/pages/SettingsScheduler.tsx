import { useEffect, useMemo, useState } from "react";
import "./settings.css";

type SchedulerTask = {
  task_id: string;
  display_name?: string | null;
  task_kind?: string | null;
  schedule_name?: string | null;
  schedule_detail?: string | null;
  status?: string | null;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  next_run_at?: string | null;
  last_error?: string | null;
};

type SchedulerSnapshot = {
  configured?: boolean;
  scheduler_status?: string;
  tasks?: Record<string, SchedulerTask>;
  schedule_catalog?: Array<{ name?: string; detail?: string }>;
};

const TASK_KIND_LABELS: Record<string, string> = {
  local_recurring: "Runtime",
  provider_specific_recurring: "Provider",
  runtime_recurring: "Runtime",
  provider_recurring: "Provider",
  system_recurring: "System",
  governance_recurring: "Governance",
  trust_recurring: "Trust",
  messaging_recurring: "Messaging",
  execution_recurring: "Execution",
  budget_recurring: "Budget",
  storage_recurring: "Storage",
  diagnostics_recurring: "Diagnostics",
  security_recurring: "Security",
};

const SCHEDULE_LABELS: Record<string, string> = {
  interval_seconds: "General Interval",
  daily: "Daily",
  weekly: "Weekly",
  "4_times_a_day": "4 Times A Day",
  every_5_minutes: "Every 5 Minutes",
  hourly: "Hourly",
  bi_weekly: "Bi-Weekly",
  monthly: "Monthly",
  every_other_day: "Every Other Day",
  twice_a_week: "Twice A Week",
  on_start: "On Start",
  every_10_seconds: "Every 10 Seconds",
  heartbeat_5_seconds: "Heartbeat 5 Seconds",
  telemetry_60_seconds: "Telemetry 60 Seconds",
};

const SCHEDULE_SORT_ORDER: Record<string, number> = {
  heartbeat_5_seconds: 5,
  every_10_seconds: 10,
  telemetry_60_seconds: 60,
  every_5_minutes: 300,
  hourly: 3600,
  "4_times_a_day": 21600,
  daily: 86400,
  every_other_day: 172800,
  twice_a_week: 302400,
  weekly: 604800,
  bi_weekly: 1209600,
  monthly: 2678400,
  on_start: 900000000,
  interval_seconds: 1000000000,
};

function formatTimestamp(value?: string | null): string {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "none";
  }
  const parsed = Date.parse(normalized);
  if (Number.isNaN(parsed)) {
    return normalized;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(parsed));
}

function friendlyTaskKind(value?: string | null): string {
  const normalized = String(value || "").trim().toLowerCase();
  return TASK_KIND_LABELS[normalized] || normalized.replaceAll("_", " ") || "-";
}

function friendlyScheduleName(value?: string | null): string {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "-";
  }
  return SCHEDULE_LABELS[normalized] || normalized.replaceAll("_", " ");
}

function sortScheduleCatalog(entries: Array<{ name?: string; detail?: string }>) {
  return [...entries].sort((left, right) => {
    const leftName = String(left?.name || "").trim();
    const rightName = String(right?.name || "").trim();
    const leftOrder = SCHEDULE_SORT_ORDER[leftName] ?? 950000000;
    const rightOrder = SCHEDULE_SORT_ORDER[rightName] ?? 950000000;
    if (leftOrder !== rightOrder) {
      return leftOrder - rightOrder;
    }
    if (leftName === "interval_seconds" && rightName !== "interval_seconds") {
      return 1;
    }
    if (rightName === "interval_seconds" && leftName !== "interval_seconds") {
      return -1;
    }
    return leftName.localeCompare(rightName);
  });
}

function statusClass(value?: string | null): string {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return "settings-state";
  return `settings-state settings-state-${normalized}`;
}

export default function SettingsScheduler() {
  const [snapshot, setSnapshot] = useState<SchedulerSnapshot | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function loadSnapshot() {
    setErr(null);
    setLoading(true);
    try {
      const res = await fetch("/api/system/scheduler/internal", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSnapshot((await res.json()) as SchedulerSnapshot);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
      setSnapshot(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadSnapshot();
    const id = window.setInterval(() => {
      void loadSnapshot();
    }, 10000);
    return () => window.clearInterval(id);
  }, []);

  const tasks = useMemo(() => {
    const items = snapshot?.tasks && typeof snapshot.tasks === "object"
      ? Object.values(snapshot.tasks)
      : [];
    return items.sort((left, right) =>
      String(left?.display_name || left?.task_id || "").localeCompare(String(right?.display_name || right?.task_id || ""))
    );
  }, [snapshot?.tasks]);

  const scheduleCatalog = useMemo(() => {
    const entries = Array.isArray(snapshot?.schedule_catalog) ? snapshot?.schedule_catalog : [];
    return sortScheduleCatalog(entries);
  }, [snapshot?.schedule_catalog]);

  return (
    <div className="settings-page">
      <h1 className="settings-title">Settings / Scheduler</h1>
      <p className="settings-muted">Scheduled tasks running inside Core, including the Supervisor heartbeat probe.</p>

      {err && <div className="settings-error">Failed to load scheduler data: {err}</div>}

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Scheduled Tasks</h2>
          <p>Scheduler-driven background jobs with current cadence and latest execution state.</p>
        </div>
        <div className="settings-card">
          <div className="settings-row">
            <div className="settings-help">Status: {snapshot?.scheduler_status || "unknown"}</div>
            <div className="settings-row-actions">
              <button className="settings-btn" onClick={() => void loadSnapshot()} disabled={loading}>
                {loading ? "Refreshing..." : "Refresh scheduler"}
              </button>
            </div>
          </div>
          {tasks.length ? (
            <table className="settings-table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Type</th>
                  <th>Schedule</th>
                  <th>Status</th>
                  <th>Last Success</th>
                  <th>Last Failure</th>
                  <th>Next Run</th>
                  <th>Last Error</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task.task_id}>
                    <td><strong>{task.display_name || task.task_id}</strong></td>
                    <td>{friendlyTaskKind(task.task_kind)}</td>
                    <td>
                      <div><strong>{friendlyScheduleName(task.schedule_name)}</strong></div>
                      <div className="settings-help">{task.schedule_detail || "-"}</div>
                    </td>
                    <td><span className={statusClass(task.status)}>{task.status || "unknown"}</span></td>
                    <td>{formatTimestamp(task.last_success_at)}</td>
                    <td>{formatTimestamp(task.last_failure_at)}</td>
                    <td>{formatTimestamp(task.next_run_at)}</td>
                    <td>{task.last_error || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="settings-help">No scheduled task data is available yet.</div>
          )}
        </div>
      </section>

      {scheduleCatalog.length ? (
        <section className="settings-section">
          <div className="settings-section-head">
            <h2>Schedule Catalog</h2>
            <p>Canonical schedule definitions used by Core scheduled tasks.</p>
          </div>
          <div className="settings-card">
            <div className="settings-kv-grid">
              {scheduleCatalog.map((entry) => (
                <div key={entry.name} className="settings-kv-item">
                  <div className="settings-label-text">{friendlyScheduleName(entry.name)}</div>
                  <div className="settings-help">{entry.detail || "-"}</div>
                </div>
              ))}
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}

import { useEffect, useState } from "react";
import "./settings.css";
import AdminReloadCard from "./settings/AdminReloadCard";
import RegistryAdminCard from "./settings/RegistryAdminCard";
import ControlPlaneCard from "./settings/ControlPlaneCard";
import UserManagementCard from "./settings/UserManagementCard";
import MqttAdminFoundationCard from "./settings/MqttAdminFoundationCard";
import { getTheme, setTheme as applyTheme } from "../../theme/theme";
import { DEFAULT_PLATFORM_CORE_NAME, usePlatformBranding } from "../branding";

type SettingsResponse = {
  ok: boolean;
  settings?: Record<string, unknown>;
  error?: string;
};

type StackSummary = {
  subsystems?: {
    core?: { state?: string };
    supervisor?: { state?: string };
    scheduler?: { state?: string; active_leases?: number; queued_jobs?: number };
    workers?: { state?: string; active_count?: number };
  };
  connectivity?: {
    network?: { state?: string };
    internet?: { state?: string };
  };
};

type MqttStatus = {
  connected?: boolean;
  mode?: string | null;
  host?: string | null;
  port?: number | null;
  last_error?: string | null;
  message_count?: number;
  last_message_at?: string | null;
};

type MqttSetupSummary = {
  ok?: boolean;
  setup?: {
    requires_setup?: boolean;
    setup_complete?: boolean;
    setup_status?: string;
    direct_mqtt_supported?: boolean;
    setup_error?: string | null;
  };
  broker?: {
    broker_mode?: string;
    direct_mqtt_supported?: boolean;
  };
  health?: MqttStatus;
  effective_status?: {
    status?: string;
    reasons?: string[];
    runtime_connected?: boolean;
    authority_ready?: boolean;
    setup_ready?: boolean;
    bootstrap_publish_ready?: boolean;
  };
  reconciliation?: {
    last_reconcile_at?: string | null;
    last_reconcile_reason?: string | null;
    last_reconcile_status?: string | null;
    last_reconcile_error?: string | null;
    last_runtime_state?: string | null;
  };
  bootstrap_publish?: {
    attempts?: number;
    successes?: number;
    last_attempt_at?: string | null;
    last_success_at?: string | null;
    last_error?: string | null;
    published?: boolean;
  };
  last_provisioning_errors?: Array<{
    addon_id?: string;
    status?: string;
    last_error?: string | null;
    updated_at?: string;
  }>;
};

type NodeOnboardingSessionSummary = {
  session_id: string;
  session_state: string;
  node_name?: string;
  node_type?: string;
  node_software_version?: string;
  requested_node_name: string;
  requested_node_type: string;
  requested_node_software_version: string;
  requested_hostname?: string | null;
  created_at: string;
  expires_at: string;
  approved_by_user_id?: string | null;
  linked_node_id?: string | null;
  rejection_reason?: string | null;
  final_payload_consumed_at?: string | null;
};

function displayState(value: unknown): string {
  const raw = String(value || "unknown").trim();
  if (!raw) return "Unknown";
  const normalized = raw.replace(/_/g, " ").toLowerCase();
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function relative(ts?: string | null): string {
  if (!ts) return "No recent message recorded";
  const t = Date.parse(ts);
  if (!Number.isFinite(t)) return ts;
  const deltaS = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (deltaS < 60) return `${deltaS}s ago`;
  if (deltaS < 3600) return `${Math.floor(deltaS / 60)}m ago`;
  if (deltaS < 86400) return `${Math.floor(deltaS / 3600)}h ago`;
  return `${Math.floor(deltaS / 86400)}d ago`;
}

export default function Settings() {
  const { coreName } = usePlatformBranding();
  const [appName, setAppName] = useState(DEFAULT_PLATFORM_CORE_NAME);
  const [maintenanceMode, setMaintenanceMode] = useState(false);
  const [theme, setTheme] = useState("dark");
  const [err, setErr] = useState<string | null>(null);
  const [opsErr, setOpsErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stack, setStack] = useState<StackSummary | null>(null);
  const [mqtt, setMqtt] = useState<MqttStatus | null>(null);
  const [mqttSetup, setMqttSetup] = useState<MqttSetupSummary | null>(null);
  const [onboardingSessions, setOnboardingSessions] = useState<NodeOnboardingSessionSummary[]>([]);
  const [onboardingStateFilter, setOnboardingStateFilter] = useState("all");
  const [onboardingErr, setOnboardingErr] = useState<string | null>(null);

  async function loadSettings() {
    setErr(null);
    try {
      const res = await fetch("/api/system/settings");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = (await res.json()) as SettingsResponse;
      if (!payload.ok) throw new Error(payload.error || "settings_unavailable");
      const settings = payload.settings || {};
      if (typeof settings["app.name"] === "string") {
        setAppName(settings["app.name"] as string);
      }
      if (typeof settings["app.maintenance_mode"] === "boolean") {
        setMaintenanceMode(settings["app.maintenance_mode"] as boolean);
      }
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    }
  }

  async function saveSettings() {
    setErr(null);
    setBusy(true);
    try {
      const updates: Array<{ key: string; value: unknown }> = [
        { key: "app.name", value: appName },
        { key: "app.maintenance_mode", value: maintenanceMode },
      ];

      for (const item of updates) {
        const res = await fetch(`/api/system/settings/${encodeURIComponent(item.key)}`, {
          method: "PUT",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ value: item.value }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      }
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  async function loadOperationalSummary() {
    setOpsErr(null);
    try {
      const [stackRes, mqttRes, mqttSetupRes] = await Promise.all([
        fetch("/api/system/stack/summary", { cache: "no-store" }),
        fetch("/api/system/mqtt/status", { cache: "no-store" }),
        fetch("/api/system/mqtt/setup-summary", { cache: "no-store" }),
      ]);
      if (!stackRes.ok) throw new Error(`stack HTTP ${stackRes.status}`);
      if (!mqttRes.ok) throw new Error(`mqtt HTTP ${mqttRes.status}`);
      if (!mqttSetupRes.ok) throw new Error(`mqtt_setup HTTP ${mqttSetupRes.status}`);
      setStack((await stackRes.json()) as StackSummary);
      setMqtt((await mqttRes.json()) as MqttStatus);
      setMqttSetup((await mqttSetupRes.json()) as MqttSetupSummary);
    } catch (e: any) {
      setOpsErr(e?.message ?? String(e));
      setStack(null);
      setMqtt(null);
      setMqttSetup(null);
    }
  }

  async function loadOnboardingSessions(stateFilter = onboardingStateFilter) {
    setOnboardingErr(null);
    try {
      const qp = stateFilter && stateFilter !== "all" ? `?state=${encodeURIComponent(stateFilter)}` : "";
      const res = await fetch(`/api/system/nodes/onboarding/sessions${qp}`, {
        credentials: "include",
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`onboarding HTTP ${res.status}`);
      const payload = (await res.json()) as { items?: NodeOnboardingSessionSummary[] };
      setOnboardingSessions(Array.isArray(payload.items) ? payload.items : []);
    } catch (e: any) {
      setOnboardingErr(e?.message ?? String(e));
      setOnboardingSessions([]);
    }
  }

  useEffect(() => {
    void loadSettings();
    void loadOperationalSummary();
    void loadOnboardingSessions("all");
    setTheme(getTheme());
  }, []);

  useEffect(() => {
    setAppName((current) => (current === DEFAULT_PLATFORM_CORE_NAME ? coreName : current));
  }, [coreName]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const payload = event.data;
      if (!payload || typeof payload !== "object") return;
      const eventType = String((payload as { type?: string }).type || "").trim();
      if (eventType !== "hexe.node_onboarding.decided") return;
      void loadOnboardingSessions(onboardingStateFilter);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [onboardingStateFilter]);

  return (
    <div className="settings-page">
      <h1 className="settings-title">Settings / Control Plane</h1>
      <p className="settings-page-subtitle">
        Manage product-facing configuration, platform visibility, and admin tools from one structured control plane.
      </p>
      <p className="settings-muted">
        Current sections are implemented on this page. Future split targets: General, Platform, Connectivity, Addons,
        Security, and Developer routes.
      </p>

      {err && <div className="settings-error">Failed to load settings: {err}</div>}
      {opsErr && <div className="settings-error">Failed to load runtime summary: {opsErr}</div>}

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>General</h2>
          <p>Product-facing defaults used across the Core UI and operator workflows.</p>
        </div>
        <div className="settings-card">
          <div className="settings-form">
            <label className="settings-label">
              <div className="settings-label-text">Application name</div>
              <div className="settings-help">Displayed in system identity and operator-facing UI context.</div>
              <input value={appName} onChange={(e) => setAppName(e.target.value)} className="settings-input" />
            </label>
            <label className="settings-label">
              <div className="settings-label-text">Theme</div>
              <div className="settings-help">Sets the active visual theme for the current control-plane session.</div>
              <select
                value={theme}
                onChange={(e) => {
                  const nextTheme = e.target.value;
                  setTheme(nextTheme);
                  applyTheme(nextTheme);
                }}
                className="settings-select-input"
              >
                <option value="dark">Dark</option>
                <option value="light">Light</option>
              </select>
            </label>
            <label className="settings-toggle">
              <input type="checkbox" checked={maintenanceMode} onChange={(e) => setMaintenanceMode(e.target.checked)} />
              <span>Maintenance mode</span>
            </label>
            <div className="settings-help">Restricts non-admin usage while maintenance or upgrades are in progress.</div>
            <div className="settings-row-actions">
              <button className="settings-btn" onClick={saveSettings} disabled={busy}>
                {busy ? "Saving..." : "Save general settings"}
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Platform</h2>
          <p>Runtime and control-plane status for Core services and scheduler activity.</p>
        </div>
        <div className="settings-card">
          <div className="settings-kv-grid">
            <div className="settings-kv-item">
              <div className="settings-label-text">Core API endpoint</div>
              <div className="settings-mono">{window.location.origin}/api</div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Supervisor</div>
              <span className="settings-pill">{displayState(stack?.subsystems?.supervisor?.state)}</span>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Core backend</div>
              <span className="settings-pill">{displayState(stack?.subsystems?.core?.state)}</span>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Scheduler</div>
              <span className="settings-pill">{displayState(stack?.subsystems?.scheduler?.state)}</span>
              <div className="settings-help">
                Active leases {Number(stack?.subsystems?.scheduler?.active_leases ?? 0)} • Queued jobs{" "}
                {Number(stack?.subsystems?.scheduler?.queued_jobs ?? 0)}
              </div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Workers</div>
              <span className="settings-pill">{displayState(stack?.subsystems?.workers?.state)}</span>
              <div className="settings-help">Active workers {Number(stack?.subsystems?.workers?.active_count ?? 0)}</div>
            </div>
          </div>
          <div className="settings-row-actions">
            <button className="settings-btn" onClick={() => void loadOperationalSummary()}>
              Refresh platform summary
            </button>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Connectivity</h2>
          <p>Current MQTT and network reachability signals from Core runtime telemetry.</p>
        </div>
        <div className="settings-card">
          <div className="settings-kv-grid">
            <div className="settings-kv-item">
              <div className="settings-label-text">Authority state</div>
              <span className="settings-pill">{displayState(mqttSetup?.effective_status?.status)}</span>
              <div className="settings-help">
                {mqttSetup?.effective_status?.reasons?.length
                  ? `Reasons: ${mqttSetup.effective_status.reasons.join(" | ")}`
                  : "No degraded reasons reported"}
              </div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">MQTT state</div>
              <span className="settings-pill">{mqtt?.connected ? "Connected" : "Disconnected"}</span>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">MQTT endpoint</div>
              <div className="settings-mono">
                {mqtt?.host ? `${mqtt.host}:${mqtt?.port ?? "-"}` : "Not configured"}
              </div>
              <div className="settings-help">Mode: {mqtt?.mode || "unknown"}</div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">MQTT traffic</div>
              <div>{Number(mqtt?.message_count ?? 0)} messages</div>
              <div className="settings-help">Last message {relative(mqtt?.last_message_at)}</div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">MQTT setup state</div>
              <span className="settings-pill">{displayState(mqttSetup?.setup?.setup_status)}</span>
              <div className="settings-help">
                {mqttSetup?.setup?.requires_setup ? "Setup required" : "Setup optional"} •{" "}
                {mqttSetup?.setup?.setup_complete ? "Setup complete" : "Setup incomplete"}
              </div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Broker capabilities</div>
              <div>Mode {displayState(mqttSetup?.broker?.broker_mode || mqtt?.mode)}</div>
              <div className="settings-help">
                Direct MQTT support {mqttSetup?.broker?.direct_mqtt_supported ? "available" : "not available"}
              </div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Last apply / reload</div>
              <span className="settings-pill">{displayState(mqttSetup?.reconciliation?.last_reconcile_status)}</span>
              <div className="settings-help">
                Reason {mqttSetup?.reconciliation?.last_reconcile_reason || "-"} • Runtime{" "}
                {displayState(mqttSetup?.reconciliation?.last_runtime_state)}
              </div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Bootstrap publish</div>
              <span className="settings-pill">{mqttSetup?.bootstrap_publish?.published ? "Published" : "Pending"}</span>
              <div className="settings-help">
                Attempts {Number(mqttSetup?.bootstrap_publish?.attempts || 0)} • Last error{" "}
                {mqttSetup?.bootstrap_publish?.last_error || "none"}
              </div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Network reachability</div>
              <span className="settings-pill">{displayState(stack?.connectivity?.network?.state)}</span>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Internet reachability</div>
              <span className="settings-pill">{displayState(stack?.connectivity?.internet?.state)}</span>
            </div>
          </div>
          {!!mqttSetup?.last_provisioning_errors?.length && (
            <div className="settings-help">
              Last provisioning errors:{" "}
              {mqttSetup.last_provisioning_errors
                .slice(0, 3)
                .map((item) => `${item.addon_id || "unknown"} (${item.status || "error"}): ${item.last_error || "unknown"}`)
                .join(" | ")}
            </div>
          )}
          {mqttSetup?.setup?.setup_error && <div className="settings-help">Setup error: {mqttSetup.setup.setup_error}</div>}
          {mqtt?.last_error && <div className="settings-help">Latest MQTT error: {mqtt.last_error}</div>}
          <div className="settings-row-actions">
            <button className="settings-btn" onClick={() => void loadOperationalSummary()}>
              Refresh connectivity status
            </button>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>MQTT Infrastructure Admin</h2>
          <p>Embedded MQTT authority administration views for principals, access, runtime health, and audit signals.</p>
        </div>
        <MqttAdminFoundationCard />
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Node Onboarding Operations</h2>
          <p>Visibility into pending, approved, rejected, expired, and consumed node registration sessions.</p>
        </div>
        <div className="settings-card">
          <div className="settings-row settings-onboarding-controls">
            <label className="settings-select">
              <span>Filter state</span>
              <select
                value={onboardingStateFilter}
                onChange={(e) => {
                  const next = e.target.value;
                  setOnboardingStateFilter(next);
                  void loadOnboardingSessions(next);
                }}
              >
                <option value="all">all</option>
                <option value="pending">pending</option>
                <option value="approved">approved</option>
                <option value="rejected">rejected</option>
                <option value="expired">expired</option>
                <option value="consumed">consumed</option>
              </select>
            </label>
            <button className="settings-btn" onClick={() => void loadOnboardingSessions()}>
              Refresh node sessions
            </button>
          </div>
          {onboardingErr && <div className="settings-error">Onboarding sessions load failed: {onboardingErr}</div>}
          <div className="settings-onboarding-list">
            {onboardingSessions.map((item) => (
              <div key={item.session_id} className="settings-onboarding-item">
                <div className="settings-onboarding-top">
                  <span className="settings-mono">{item.session_id}</span>
                  <span className="settings-pill">{displayState(item.session_state)}</span>
                </div>
                <div className="settings-help">
                  {(item.node_name || item.requested_node_name)} ({(item.node_type || item.requested_node_type)}) • version{" "}
                  {(item.node_software_version || item.requested_node_software_version)} • hostname{" "}
                  {item.requested_hostname || "-"}
                </div>
                <div className="settings-help">
                  Created {relative(item.created_at)} • Expires {relative(item.expires_at)}
                </div>
                <div className="settings-help">
                  Decision actor {item.approved_by_user_id || "-"} • Linked node {item.linked_node_id || "-"}
                  {item.rejection_reason ? ` • Rejection: ${item.rejection_reason}` : ""}
                  {item.final_payload_consumed_at ? ` • Consumed ${relative(item.final_payload_consumed_at)}` : ""}
                </div>
              </div>
            ))}
            {onboardingSessions.length === 0 && <div className="settings-help">No onboarding sessions found for this filter.</div>}
          </div>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Addon Registry</h2>
          <p>Managed addon endpoint inventory for registration, health, and capability metadata.</p>
        </div>
        <RegistryAdminCard />
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Security / Access</h2>
          <p>Administrative account lifecycle controls for operator access management.</p>
        </div>
        <UserManagementCard />
      </section>

      <section className="settings-section settings-section-dev">
        <div className="settings-section-head">
          <h2>Developer Tools</h2>
          <p>Development and deep-diagnostic controls. Keep disabled for normal operator workflows.</p>
        </div>
        <details className="settings-dev-collapsible">
          <summary>Show development controls</summary>
          <div className="settings-dev-body">
            <AdminReloadCard />
            <ControlPlaneCard />
          </div>
        </details>
      </section>
    </div>
  );
}

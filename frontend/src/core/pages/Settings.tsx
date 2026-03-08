import { useEffect, useState } from "react";
import "./settings.css";
import AdminReloadCard from "./settings/AdminReloadCard";
import RegistryAdminCard from "./settings/RegistryAdminCard";
import ControlPlaneCard from "./settings/ControlPlaneCard";
import UserManagementCard from "./settings/UserManagementCard";
import { getTheme, setTheme as applyTheme } from "../../theme/theme";

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
  const [appName, setAppName] = useState("Synthia Core");
  const [maintenanceMode, setMaintenanceMode] = useState(false);
  const [theme, setTheme] = useState("dark");
  const [err, setErr] = useState<string | null>(null);
  const [opsErr, setOpsErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stack, setStack] = useState<StackSummary | null>(null);
  const [mqtt, setMqtt] = useState<MqttStatus | null>(null);
  const [mqttMode, setMqttMode] = useState<"local" | "external">("local");
  const [mqttHost, setMqttHost] = useState("");
  const [mqttPort, setMqttPort] = useState("1883");
  const [mqttUsername, setMqttUsername] = useState("");
  const [mqttPassword, setMqttPassword] = useState("");
  const [mqttTlsEnabled, setMqttTlsEnabled] = useState(false);
  const [mqttKeepalive, setMqttKeepalive] = useState("30");
  const [mqttClientId, setMqttClientId] = useState("synthia-core");
  const [mqttBusy, setMqttBusy] = useState(false);

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
      const mode = String(settings["mqtt.mode"] || "local").toLowerCase();
      const normalizedMode: "local" | "external" = mode === "external" ? "external" : "local";
      setMqttMode(normalizedMode);
      const hostKey = `mqtt.${normalizedMode}.host`;
      const portKey = `mqtt.${normalizedMode}.port`;
      const userKey = `mqtt.${normalizedMode}.username`;
      const passKey = `mqtt.${normalizedMode}.password`;
      const tlsKey = `mqtt.${normalizedMode}.tls_enabled`;
      setMqttHost(
        typeof settings[hostKey] === "string"
          ? (settings[hostKey] as string)
          : normalizedMode === "local"
            ? "127.0.0.1"
            : "",
      );
      setMqttPort(String(settings[portKey] ?? 1883));
      setMqttUsername(typeof settings[userKey] === "string" ? (settings[userKey] as string) : "");
      setMqttPassword(typeof settings[passKey] === "string" ? (settings[passKey] as string) : "");
      setMqttTlsEnabled(Boolean(settings[tlsKey]));
      setMqttKeepalive(String(settings["mqtt.keepalive_s"] ?? 30));
      setMqttClientId(typeof settings["mqtt.client_id"] === "string" ? (settings["mqtt.client_id"] as string) : "synthia-core");
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
      const [stackRes, mqttRes] = await Promise.all([
        fetch("/api/system/stack/summary", { cache: "no-store" }),
        fetch("/api/system/mqtt/status", { cache: "no-store" }),
      ]);
      if (!stackRes.ok) throw new Error(`stack HTTP ${stackRes.status}`);
      if (!mqttRes.ok) throw new Error(`mqtt HTTP ${mqttRes.status}`);
      setStack((await stackRes.json()) as StackSummary);
      setMqtt((await mqttRes.json()) as MqttStatus);
    } catch (e: any) {
      setOpsErr(e?.message ?? String(e));
      setStack(null);
      setMqtt(null);
    }
  }

  async function saveMqttSettings(restartAfterSave: boolean) {
    setErr(null);
    setMqttBusy(true);
    const selectedMode = mqttMode === "external" ? "external" : "local";
    const hostKey = `mqtt.${selectedMode}.host`;
    const portKey = `mqtt.${selectedMode}.port`;
    const userKey = `mqtt.${selectedMode}.username`;
    const passKey = `mqtt.${selectedMode}.password`;
    const tlsKey = `mqtt.${selectedMode}.tls_enabled`;
    const parsedPort = Number.parseInt(mqttPort.trim(), 10);
    const parsedKeepalive = Number.parseInt(mqttKeepalive.trim(), 10);
    if (!Number.isFinite(parsedPort) || parsedPort <= 0 || parsedPort > 65535) {
      setErr("Invalid MQTT port. Expected 1-65535.");
      setMqttBusy(false);
      return;
    }
    if (!Number.isFinite(parsedKeepalive) || parsedKeepalive <= 0) {
      setErr("Invalid keepalive value. Expected a positive integer.");
      setMqttBusy(false);
      return;
    }
    try {
      const updates: Array<{ key: string; value: unknown }> = [
        { key: "mqtt.mode", value: selectedMode },
        { key: hostKey, value: mqttHost.trim() },
        { key: portKey, value: parsedPort },
        { key: userKey, value: mqttUsername.trim() },
        { key: passKey, value: mqttPassword },
        { key: tlsKey, value: mqttTlsEnabled },
        { key: "mqtt.keepalive_s", value: parsedKeepalive },
        { key: "mqtt.client_id", value: mqttClientId.trim() || "synthia-core" },
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
      if (restartAfterSave) {
        const restartRes = await fetch("/api/system/mqtt/restart", {
          method: "POST",
          credentials: "include",
        });
        if (!restartRes.ok) throw new Error(`mqtt_restart_http_${restartRes.status}`);
      }
      await loadOperationalSummary();
      await loadSettings();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setMqttBusy(false);
    }
  }

  useEffect(() => {
    void loadSettings();
    void loadOperationalSummary();
    setTheme(getTheme());
  }, []);

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
              <div className="settings-label-text">Network reachability</div>
              <span className="settings-pill">{displayState(stack?.connectivity?.network?.state)}</span>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Internet reachability</div>
              <span className="settings-pill">{displayState(stack?.connectivity?.internet?.state)}</span>
            </div>
          </div>
          {mqtt?.last_error && <div className="settings-help">Latest MQTT error: {mqtt.last_error}</div>}
          <div className="settings-connectivity-config">
            <div className="settings-card-title">MQTT Setup</div>
            <div className="settings-help">Configure broker connection and apply changes to the Core MQTT manager.</div>
            <div className="settings-form">
              <label className="settings-label">
                <div className="settings-label-text">Mode</div>
                <select
                  value={mqttMode}
                  onChange={(e) => setMqttMode(e.target.value === "external" ? "external" : "local")}
                  className="settings-select-input"
                >
                  <option value="local">Local broker</option>
                  <option value="external">External broker</option>
                </select>
              </label>
              <label className="settings-label">
                <div className="settings-label-text">Host</div>
                <input value={mqttHost} onChange={(e) => setMqttHost(e.target.value)} className="settings-input" />
              </label>
              <label className="settings-label">
                <div className="settings-label-text">Port</div>
                <input value={mqttPort} onChange={(e) => setMqttPort(e.target.value)} className="settings-input" />
              </label>
              <label className="settings-label">
                <div className="settings-label-text">Username (optional)</div>
                <input value={mqttUsername} onChange={(e) => setMqttUsername(e.target.value)} className="settings-input" />
              </label>
              <label className="settings-label">
                <div className="settings-label-text">Password (optional)</div>
                <input
                  type="password"
                  value={mqttPassword}
                  onChange={(e) => setMqttPassword(e.target.value)}
                  className="settings-input"
                />
              </label>
              <label className="settings-toggle">
                <input type="checkbox" checked={mqttTlsEnabled} onChange={(e) => setMqttTlsEnabled(e.target.checked)} />
                <span>TLS enabled</span>
              </label>
              <label className="settings-label">
                <div className="settings-label-text">Keepalive (seconds)</div>
                <input
                  value={mqttKeepalive}
                  onChange={(e) => setMqttKeepalive(e.target.value)}
                  className="settings-input"
                />
              </label>
              <label className="settings-label">
                <div className="settings-label-text">Client ID</div>
                <input value={mqttClientId} onChange={(e) => setMqttClientId(e.target.value)} className="settings-input" />
              </label>
            </div>
            <div className="settings-row-actions">
              <button className="settings-btn" onClick={() => void saveMqttSettings(false)} disabled={mqttBusy}>
                {mqttBusy ? "Applying..." : "Apply MQTT settings"}
              </button>
              <button className="settings-btn" onClick={() => void saveMqttSettings(true)} disabled={mqttBusy}>
                {mqttBusy ? "Applying..." : "Apply and restart MQTT"}
              </button>
            </div>
          </div>
          <div className="settings-row-actions">
            <button className="settings-btn" onClick={() => void loadOperationalSummary()}>
              Refresh connectivity status
            </button>
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

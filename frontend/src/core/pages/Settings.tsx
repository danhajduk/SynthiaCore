import { useEffect, useState } from "react";
import "./settings.css";

type SettingsResponse = {
  ok: boolean;
  settings?: Record<string, unknown>;
  error?: string;
};

export default function Settings() {
  const [appName, setAppName] = useState("Synthia Core");
  const [maintenanceMode, setMaintenanceMode] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
          headers: { "Content-Type": "application/json" },
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

  useEffect(() => {
    loadSettings();
  }, []);

  return (
    <div>
      <h1 className="settings-title">Settings</h1>
      <p>Core application settings.</p>

      {err && <div className="settings-error">Failed to load settings: {err}</div>}

      <div className="settings-card">
        <div className="settings-card-title">App</div>
        <div className="settings-form">
          <label className="settings-label">
            <div className="settings-label-text">App name</div>
            <input
              value={appName}
              onChange={(e) => setAppName(e.target.value)}
              className="settings-input"
            />
          </label>
          <label className="settings-toggle">
            <input
              type="checkbox"
              checked={maintenanceMode}
              onChange={(e) => setMaintenanceMode(e.target.checked)}
            />
            <span>Maintenance mode</span>
          </label>
          <div className="settings-row-actions">
            <button className="settings-btn" onClick={saveSettings} disabled={busy}>
              Save settings
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

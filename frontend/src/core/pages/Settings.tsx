import SystemStatsWidget from "../../components/SystemStatsWidget";
import AdminReloadCard from "./settings/AdminReloadCard";
import "./settings.css";

export default function Settings() {
  const showDevTools = import.meta.env.DEV;

  return (
    <div>
      <h1 className="settings-title">Settings</h1>
      <p>Placeholder system settings page.</p>

      <hr className="settings-hr" />

      <h2>System</h2>
      <p className="settings-muted">
        Live system and API health metrics.
      </p>

      <SystemStatsWidget />

      {showDevTools && (
        <>
          <hr className="settings-hr-wide" />
          <h2>Developer Tools</h2>
          <AdminReloadCard />
        </>
      )}
    </div>
  );
}

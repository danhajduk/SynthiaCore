import SystemStatsWidget from "../../components/SystemStatsWidget";
import AdminReloadCard from "./settings/AdminReloadCard";

export default function Settings() {
  const showDevTools = import.meta.env.DEV;

  return (
    <div >
      <h1 style={{ marginTop: 0 }}>Settings</h1>
      <p>Placeholder system settings page.</p>

      <hr style={{ margin: "24px 0", opacity: 0.25 }} />

      <h2>System</h2>
      <p style={{ opacity: 0.7 }}>
        Live system and API health metrics.
      </p>

      <SystemStatsWidget />

      {showDevTools && (
        <>
          <hr style={{ margin: "32px 0", opacity: 0.25 }} />
          <h2>Developer Tools</h2>
          <AdminReloadCard />
        </>
      )}
    </div>
  );
}

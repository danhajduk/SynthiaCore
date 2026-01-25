import AdminReloadCard from "./settings/AdminReloadCard";

export default function Settings() {
  const showDevTools = import.meta.env.DEV;

  return (
    <div style={{ maxWidth: 900 }}>
      <h1 style={{ marginTop: 0 }}>Settings</h1>
      <p>Placeholder system settings page.</p>

      {showDevTools && (
        <>
          <hr style={{ margin: "24px 0", opacity: 0.25 }} />
          <AdminReloadCard />
        </>
      )}
    </div>
  );
}

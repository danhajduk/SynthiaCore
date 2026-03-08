import { useEffect, useState } from "react";
import "./admin-reload-card.css";

type AdminUser = {
  username: string;
  role: string;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
};

export default function UserManagementCard() {
  const [items, setItems] = useState<AdminUser[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("guest");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function loadUsers() {
    setErr(null);
    try {
      const res = await fetch("/api/admin/users", { credentials: "include" });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status} ${txt}`);
      }
      const payload = (await res.json()) as { items?: AdminUser[] };
      setItems(Array.isArray(payload.items) ? payload.items : []);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
      setItems([]);
    }
  }

  async function createOrUpdate() {
    if (!username.trim()) return;
    setErr(null);
    setBusy(true);
    try {
      const res = await fetch("/api/admin/users", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          username: username.trim(),
          password: password || undefined,
          role,
          enabled,
        }),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status} ${txt}`);
      }
      setPassword("");
      await loadUsers();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  async function removeUser(target: string) {
    setErr(null);
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(target)}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status} ${txt}`);
      }
      await loadUsers();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    }
  }

  useEffect(() => {
    loadUsers();
  }, []);

  return (
    <section className="admin-card">
      <div className="admin-header">
        <div>
          <div className="admin-title">User Management</div>
          <div className="admin-subtitle">Create, update, and remove admin/guest users.</div>
        </div>
      </div>

      <div className="admin-form">
        <label className="admin-label">
          <div className="admin-label-text">Username</div>
          <input value={username} onChange={(e) => setUsername(e.target.value)} className="admin-input admin-input-mono" />
        </label>
        <label className="admin-label">
          <div className="admin-label-text">Password (required for new users)</div>
          <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" className="admin-input" />
        </label>
        <label className="admin-label">
          <div className="admin-label-text">Role</div>
          <select value={role} onChange={(e) => setRole(e.target.value)} className="admin-input">
            <option value="guest">guest</option>
            <option value="admin">admin</option>
          </select>
        </label>
        <label className="admin-label">
          <div className="admin-label-text">Enabled</div>
          <input checked={enabled} onChange={(e) => setEnabled(e.target.checked)} type="checkbox" />
        </label>

        <div className="admin-actions">
          <button className="admin-btn admin-btn-primary" onClick={createOrUpdate} disabled={busy || !username.trim()}>
            {busy ? "Saving..." : "Create / Update User"}
          </button>
          <button className="admin-btn" onClick={loadUsers}>Refresh Users</button>
        </div>

        {err && <pre className="admin-error">{err}</pre>}

        <div>
          <div className="admin-log-label">Users</div>
          <div className="admin-form">
            {items.map((item) => (
              <div key={item.username} className="admin-log">
                <div><strong>{item.username}</strong> • role: {item.role} • enabled: {String(item.enabled)}</div>
                <div>created: {item.created_at ? new Date(item.created_at).toLocaleString() : "-"}</div>
                <div>updated: {item.updated_at ? new Date(item.updated_at).toLocaleString() : "-"}</div>
                <div className="admin-actions">
                  <button className="admin-btn admin-btn-muted" onClick={() => removeUser(item.username)}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
            {items.length === 0 && <div className="admin-log">No users found in the local admin store.</div>}
          </div>
        </div>
      </div>
    </section>
  );
}

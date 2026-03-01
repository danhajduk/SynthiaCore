import { useState } from "react";

import { useAdminSession } from "../auth/AdminSessionContext";
import "./home.css";

export default function Home() {
  const { authenticated, login, logout, ready } = useAdminSession();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submitLogin() {
    if (!token.trim()) {
      setErr("token_required");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const result = await login(token.trim());
      if (!result.ok) {
        setErr(result.error || "login_failed");
        return;
      }
      setToken("");
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

  return (
    <div>
      <h1 className="home-title">Home</h1>
      <p>Core shell is running. If you synced addons, they will appear in the sidebar.</p>

      <section className="home-auth-card">
        <div className="home-auth-title">Admin Access</div>
        {!ready ? (
          <div>Checking session...</div>
        ) : authenticated ? (
          <>
            <div className="home-auth-ok">Admin session is active.</div>
            <button className="home-auth-btn" onClick={submitLogout} disabled={busy}>
              {busy ? "Signing out..." : "Sign out"}
            </button>
          </>
        ) : (
          <>
            <div className="home-auth-help">Sign in with the backend admin token to unlock all routes.</div>
            <input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="SYNTHIA_ADMIN_TOKEN"
              className="home-auth-input"
            />
            <button className="home-auth-btn" onClick={submitLogin} disabled={busy || !token.trim()}>
              {busy ? "Signing in..." : "Sign in as Admin"}
            </button>
          </>
        )}
        {err && <div className="home-auth-err">{err}</div>}
      </section>
    </div>
  );
}

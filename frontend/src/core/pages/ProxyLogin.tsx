import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";

import { sanitizeNextPath } from "../auth/nextPath";
import { useAdminSession } from "../auth/AdminSessionContext";
import { usePlatformBranding } from "../branding";
import "./proxy-login.css";

export default function ProxyLogin() {
  const { authenticated, login, ready } = useAdminSession();
  const branding = usePlatformBranding();
  const location = useLocation();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const nextPath = useMemo(
    () => sanitizeNextPath(new URLSearchParams(location.search).get("next")),
    [location.search],
  );

  useEffect(() => {
    if (!ready || !authenticated) return;
    window.location.assign(nextPath);
  }, [authenticated, nextPath, ready]);

  async function submitLogin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
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
      window.location.assign(nextPath);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="proxy-login-page">
      <div className="proxy-login-shell">
        <div className="proxy-login-copy">
          <div className="proxy-login-eyebrow">Admin Access Required</div>
          <h1 className="proxy-login-title">Sign in to continue to the proxied node</h1>
          <p className="proxy-login-lead">
            This node route is protected by {branding.coreName} admin auth. Sign in once and we&apos;ll continue to the original
            proxy request automatically.
          </p>
          <div className="proxy-login-next">
            Continue to <code>{nextPath}</code>
          </div>
        </div>

        <form className="proxy-login-card" onSubmit={submitLogin}>
          <label>
            Username
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
          </label>
          <label>
            Password
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              autoComplete="current-password"
            />
          </label>
          <button className="addon-btn addon-btn-primary" type="submit" disabled={busy || !username.trim() || !password}>
            {busy ? "Signing in..." : "Sign In"}
          </button>
          {err ? <div className="proxy-login-error">{err}</div> : null}
        </form>
      </div>
    </div>
  );
}

import type { FormEvent } from "react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import successImage from "../../assets/success.png";
import workingImage from "../../assets/working.png";
import { useAdminSession } from "../auth/AdminSessionContext";
import { usePlatformBranding } from "../branding";
import "./onboarding-node-approval.css";

type EnrollmentTokenResponse = {
  enrollment_token?: string;
  one_time_token?: string;
  token?: {
    supervisor_id?: string | null;
    supervisor_name?: string | null;
    expires_at?: string | null;
  };
};

async function readError(res: Response): Promise<string> {
  try {
    const payload = await res.json();
    if (typeof payload?.detail === "string" && payload.detail.trim()) return payload.detail.trim();
    if (typeof payload?.detail?.error === "string" && payload.detail.error.trim()) return payload.detail.error.trim();
    if (typeof payload?.error === "string" && payload.error.trim()) return payload.error.trim();
  } catch {
    // Fall through to status text.
  }
  return `HTTP ${res.status}`;
}

function fmt(ts?: string | null): string {
  if (!ts) return "-";
  const n = Date.parse(ts);
  if (!Number.isFinite(n)) return ts;
  return new Date(n).toLocaleString();
}

function cleanDefault(value: string | null, fallback: string): string {
  const text = String(value || "").trim();
  return text || fallback;
}

function normalizeTtl(value: string): number {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return 900;
  return Math.min(Math.max(parsed, 60), 24 * 60 * 60);
}

function copyText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(value);
  }
  const el = document.createElement("textarea");
  el.value = value;
  el.setAttribute("readonly", "true");
  el.style.position = "fixed";
  el.style.opacity = "0";
  document.body.appendChild(el);
  el.select();
  document.execCommand("copy");
  document.body.removeChild(el);
  return Promise.resolve();
}

export default function SupervisorEnrollment() {
  const { platformName } = usePlatformBranding();
  const { ready, authenticated, login } = useAdminSession();
  const [params] = useSearchParams();
  const initialSupervisorId = cleanDefault(params.get("supervisor_id"), "");
  const initialSupervisorName = cleanDefault(params.get("supervisor_name"), initialSupervisorId);
  const returnUrl = cleanDefault(params.get("return_url"), "");

  const [supervisorId, setSupervisorId] = useState(initialSupervisorId);
  const [supervisorName, setSupervisorName] = useState(initialSupervisorName);
  const [ttlSeconds, setTtlSeconds] = useState("900");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EnrollmentTokenResponse | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginErr, setLoginErr] = useState<string | null>(null);

  const tokenValue = String(result?.enrollment_token || result?.one_time_token || "").trim();
  const effectiveSupervisorId = String(result?.token?.supervisor_id || supervisorId || "").trim();
  const coreUrl = `${window.location.protocol}//${window.location.host}`;
  const installCommand = useMemo(() => {
    if (!tokenValue || !effectiveSupervisorId) return "";
    const args = [
      "curl -fsSL https://raw.githubusercontent.com/danhajduk/HexeCore/main/core/scripts/install-supervisor.sh | bash -s --",
      "--join-core",
      `--core-url ${coreUrl}`,
      `--supervisor-id ${effectiveSupervisorId}`,
      `--enrollment-token ${tokenValue}`,
    ];
    return args.join(" \\\n  ");
  }, [coreUrl, effectiveSupervisorId, tokenValue]);

  async function submitLogin(e: FormEvent) {
    e.preventDefault();
    if (loginBusy) return;
    setLoginBusy(true);
    setLoginErr(null);
    try {
      const loginResult = await login(username.trim(), password);
      if (!loginResult.ok) {
        setLoginErr(loginResult.error || "login_failed");
        return;
      }
      setPassword("");
    } finally {
      setLoginBusy(false);
    }
  }

  async function createToken(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    setCopied(null);
    setResult(null);
    try {
      const body = {
        supervisor_id: supervisorId.trim() || null,
        supervisor_name: supervisorName.trim() || null,
        ttl_seconds: normalizeTtl(ttlSeconds),
        metadata: { source: "core_supervisor_enrollment_page" },
      };
      const res = await fetch("/api/system/supervisors/enrollment-tokens", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await readError(res));
      setResult((await res.json()) as EnrollmentTokenResponse);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function copyNamed(name: string, value: string) {
    if (!value) return;
    await copyText(value);
    setCopied(name);
    window.setTimeout(() => setCopied((current) => (current === name ? null : current)), 1600);
  }

  return (
    <section className="onboard-page">
      <div className="onboard-shell">
        <div className="onboard-header">
          <div className="onboard-eyebrow">Supervisor Enrollment</div>
          <p className="onboard-lead">Create a short-lived one-time token for a Supervisor joining this Core.</p>
        </div>

        {!ready ? (
          <div className="onboard-status-card">
            <div className="onboard-meta">Checking admin session...</div>
          </div>
        ) : !authenticated ? (
          <div className="onboard-approval-layout onboard-approval-layout-login">
            <form className="onboard-login" onSubmit={submitLogin}>
              <div className="onboard-card-top">
                <div>
                  <div className="onboard-card-kicker">Admin sign-in required</div>
                  <h2 className="onboard-card-title">Core Supervisor access</h2>
                </div>
                <div className="onboard-state-pill">Pending</div>
              </div>
              <div className="onboard-help">Sign in as Core admin to create the Supervisor enrollment token.</div>
              <label>
                <span>Username</span>
                <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
              </label>
              <label>
                <span>Password</span>
                <input
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  type="password"
                  autoComplete="current-password"
                />
              </label>
              <button className="addon-btn addon-btn-primary onboard-action-primary" type="submit" disabled={loginBusy}>
                {loginBusy ? "Signing in..." : "Sign In"}
              </button>
              {loginErr && <div className="onboard-error">{loginErr}</div>}
            </form>

            <aside className="onboard-presenter-panel">
              <div className="onboard-presenter-copy">
                <div className="onboard-card-kicker">Join checkpoint</div>
                <h2 className="onboard-presenter-title">Authorize this host</h2>
                <p className="onboard-lead onboard-presenter-lead">
                  {platformName} will issue a one-time token that the Supervisor exchanges for its reporting credential.
                </p>
              </div>
              <div className="onboard-presenter-frame">
                <img className="onboard-presenter-image" src={workingImage} alt={`${platformName} preparing enrollment`} />
              </div>
            </aside>
          </div>
        ) : (
          <div className="onboard-approval-layout">
            <article className="onboard-card">
              <div className="onboard-card-top">
                <div>
                  <div className="onboard-card-kicker">Supervisor Registration</div>
                  <h2 className="onboard-card-title">{supervisorId || "New Supervisor"}</h2>
                  <div className="onboard-meta">Create the join token and return it to the installing host.</div>
                </div>
                <div className={`onboard-state-pill ${tokenValue ? "onboard-state-pill-approved" : ""}`}>
                  {tokenValue ? "Token Ready" : "Draft"}
                </div>
              </div>

              <form className="onboard-card-sections" onSubmit={createToken}>
                <section className="onboard-section">
                  <div className="onboard-section-title">Identity</div>
                  <div className="onboard-field-grid">
                    <label className="onboard-field onboard-form-field">
                      <strong>Supervisor ID</strong>
                      <input
                        value={supervisorId}
                        onChange={(e) => setSupervisorId(e.target.value)}
                        placeholder="host-a-hexe-supervisor"
                      />
                    </label>
                    <label className="onboard-field onboard-form-field">
                      <strong>Supervisor Name</strong>
                      <input
                        value={supervisorName}
                        onChange={(e) => setSupervisorName(e.target.value)}
                        placeholder="Host A Supervisor"
                      />
                    </label>
                    <label className="onboard-field onboard-form-field">
                      <strong>TTL Seconds</strong>
                      <input
                        value={ttlSeconds}
                        onChange={(e) => setTtlSeconds(e.target.value)}
                        inputMode="numeric"
                        placeholder="900"
                      />
                    </label>
                    <div className="onboard-field">
                      <strong>Core URL</strong>
                      <span>{coreUrl}</span>
                    </div>
                  </div>
                </section>

                {result && (
                  <section className="onboard-section">
                    <div className="onboard-section-title">Enrollment Token</div>
                    <div className="onboard-token-output">
                      <div className="onboard-field">
                        <strong>Expires At</strong>
                        <span>{fmt(result.token?.expires_at)}</span>
                      </div>
                      <textarea readOnly value={tokenValue} aria-label="Enrollment token" />
                      <div className="onboard-actions">
                        <button
                          className="addon-btn addon-btn-primary onboard-action-primary"
                          type="button"
                          onClick={() => void copyNamed("token", tokenValue)}
                        >
                          {copied === "token" ? "Copied" : "Copy Token"}
                        </button>
                        {installCommand && (
                          <button
                            className="addon-btn onboard-action-secondary"
                            type="button"
                            onClick={() => void copyNamed("command", installCommand)}
                          >
                            {copied === "command" ? "Copied" : "Copy Join Command"}
                          </button>
                        )}
                        {returnUrl && (
                          <button className="addon-btn onboard-action-secondary" type="button" onClick={() => window.open(returnUrl, "_self")}>
                            Return To Setup
                          </button>
                        )}
                      </div>
                    </div>
                  </section>
                )}

                <div className="onboard-actions">
                  <button className="addon-btn addon-btn-primary onboard-action-primary" type="submit" disabled={busy}>
                    {busy ? "Creating..." : "Create Token"}
                  </button>
                </div>
                {error && <div className="onboard-error">{error}</div>}
              </form>
            </article>

            <aside className="onboard-presenter-panel">
              <div className="onboard-presenter-copy">
                <div className="onboard-card-kicker">{tokenValue ? "Enrollment ready" : "Join checkpoint"}</div>
                <h2 className="onboard-presenter-title">{tokenValue ? "Token created" : "Authorize this Supervisor"}</h2>
                <p className="onboard-lead onboard-presenter-lead">
                  {tokenValue
                    ? "Use the token once during install. Core stores only the issued reporting credential after enrollment."
                    : "The installing host will exchange this token, then report with a Supervisor token instead of an admin token."}
                </p>
              </div>
              <div className="onboard-presenter-frame">
                <img
                  className="onboard-presenter-image"
                  src={tokenValue ? successImage : workingImage}
                  alt={tokenValue ? `${platformName} enrollment token created` : `${platformName} waiting for enrollment`}
                />
              </div>
            </aside>
          </div>
        )}
      </div>
    </section>
  );
}

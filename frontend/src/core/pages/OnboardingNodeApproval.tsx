import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import deniedImage from "../../assets/error.png";
import expiredImage from "../../assets/oops.png";
import presentingImage from "../../assets/presenting.png";
import successImage from "../../assets/success.png";
import workingImage from "../../assets/working.png";
import { useAdminSession } from "../auth/AdminSessionContext";
import "./onboarding-node-approval.css";

type ApprovalSession = {
  session_id: string;
  session_state: string;
  node_name?: string;
  node_type?: string;
  node_software_version?: string;
  requested_node_name: string;
  requested_node_type: string;
  requested_node_software_version: string;
  requested_hostname?: string | null;
  requested_from_ip?: string | null;
  created_at: string;
  expires_at: string;
  approved_at?: string | null;
  rejected_at?: string | null;
  approved_by_user_id?: string | null;
  rejection_reason?: string | null;
  linked_node_id?: string | null;
  final_payload_consumed_at?: string | null;
};

type PresenterState = "presenting" | "working" | "success" | "expired" | "denied";

function fmt(ts?: string | null): string {
  if (!ts) return "-";
  const n = Date.parse(ts);
  if (!Number.isFinite(n)) return ts;
  return new Date(n).toLocaleString();
}

function sessionStateLabel(value?: string | null): string {
  const state = String(value || "").trim();
  return state ? state.replace(/[_-]+/g, " ") : "unknown";
}

function maskSessionId(value?: string | null): string {
  const sessionId = String(value || "").trim();
  const tail = sessionId.slice(-4) || "----";
  return `************${tail}`;
}

export default function OnboardingNodeApproval() {
  const { ready, authenticated, login } = useAdminSession();
  const [params] = useSearchParams();
  const sid = (params.get("sid") || "").trim();
  const state = (params.get("state") || "").trim();

  const [session, setSession] = useState<ApprovalSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<"approve" | "reject" | null>(null);
  const [approvalWaitMsg, setApprovalWaitMsg] = useState<string | null>(null);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginErr, setLoginErr] = useState<string | null>(null);
  const [presenterState, setPresenterState] = useState<PresenterState>("presenting");
  const currentState = String(session?.session_state || "").trim().toLowerCase();

  const query = useMemo(() => {
    const q = new URLSearchParams();
    if (state) q.set("state", state);
    return q.toString();
  }, [state]);

  const presenter = useMemo(() => {
    const effectiveState: PresenterState = (() => {
      if (["rejected", "denied", "error"].includes(currentState)) return "denied";
      if (currentState === "expired") return "expired";
      if (["approved", "consumed"].includes(currentState)) return "success";
      return presenterState;
    })();

    if (effectiveState === "denied") {
      return {
        image: deniedImage,
        alt: "Synthia reporting an onboarding error or rejection",
        eyebrow: "Approval denied",
        title: "Review required",
        copy: "This onboarding session was rejected or failed validation.",
      };
    }
    if (effectiveState === "expired") {
      return {
        image: expiredImage,
        alt: "Synthia reporting an expired onboarding session",
        eyebrow: "Session expired",
        title: "Approval window closed",
        copy: "This onboarding session expired before trust could be granted.",
      };
    }
    if (effectiveState === "working") {
      return {
        image: workingImage,
        alt: "Synthia processing node approval",
        eyebrow: "Approval in progress",
        title: "Establishing trust material",
        copy: "Core is validating approval state and waiting for node finalization.",
      };
    }
    if (effectiveState === "success") {
      return {
        image: successImage,
        alt: "Synthia approval completed successfully",
        eyebrow: "Approval complete",
        title: "Trust granted",
        copy: "The node has been approved and the flow is wrapping up.",
      };
    }
    return {
      image: presentingImage,
      alt: "Synthia presenting the node approval card",
      eyebrow: "Trust checkpoint",
      title: "Review before granting access",
      copy: "Approved nodes receive trust material and operational MQTT credentials.",
    };
  }, [currentState, presenterState]);

  function notifyParent(action: "approve" | "reject", sessionId: string) {
    try {
      if (window.opener && window.opener !== window) {
        window.opener.postMessage(
          {
            type: "synthia.node_onboarding.decided",
            action,
            session_id: sessionId,
          },
          "*",
        );
      }
    } catch {
      // Ignore cross-window messaging issues; close path still proceeds.
    }
  }

  function closeApprovalWindow() {
    window.close();
    window.location.replace("/");
  }

  async function loadSession() {
    if (!ready || !authenticated || !sid) return;
    setLoading(true);
    setError(null);
    try {
      const suffix = query ? `?${query}` : "";
      const res = await fetch(`/api/system/nodes/onboarding/sessions/${encodeURIComponent(sid)}${suffix}`, {
        credentials: "include",
        cache: "no-store",
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = typeof payload?.detail === "string" ? payload.detail : payload?.detail?.error || `HTTP ${res.status}`;
        throw new Error(detail);
      }
      setSession((payload as { session?: ApprovalSession }).session || null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setSession(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setPresenterState("presenting");
    void loadSession();
  }, [authenticated, query, ready, sid]);

  async function submitLogin(e: FormEvent) {
    e.preventDefault();
    if (loginBusy) return;
    setLoginBusy(true);
    setLoginErr(null);
    try {
      const result = await login(username.trim(), password);
      if (!result.ok) {
        setLoginErr(result.error || "login_failed");
        return;
      }
      setPassword("");
    } finally {
      setLoginBusy(false);
    }
  }

  async function waitForApprovalFinalization(sessionId: string): Promise<void> {
    const suffix = query ? `?${query}` : "";
    const deadline = Date.now() + 120_000;
    while (Date.now() < deadline) {
      const sessionRes = await fetch(
        `/api/system/nodes/onboarding/sessions/${encodeURIComponent(sessionId)}${suffix}`,
        { credentials: "include", cache: "no-store" },
      );
      const sessionBody = await sessionRes.json().catch(() => ({}));
      if (!sessionRes.ok) {
        const detail =
          typeof sessionBody?.detail === "string"
            ? sessionBody.detail
            : sessionBody?.detail?.error || `HTTP ${sessionRes.status}`;
        throw new Error(detail);
      }
      const latest = (sessionBody as { session?: ApprovalSession }).session || null;
      setSession(latest);
      const stateNow = String(latest?.session_state || "").toLowerCase();
      if (stateNow === "consumed") return;

      const linkedNodeId = String(latest?.linked_node_id || "").trim();
      if (linkedNodeId) {
        const nodeRes = await fetch("/api/system/nodes/registry", {
          credentials: "include",
          cache: "no-store",
        });
        const nodeBody = await nodeRes.json().catch(() => ({}));
        if (nodeRes.ok) {
          const items = Array.isArray((nodeBody as { items?: unknown[] }).items)
            ? ((nodeBody as { items?: Array<Record<string, unknown>> }).items as Array<Record<string, unknown>>)
            : [];
          const node = items.find((item) => String(item?.node_id || "").trim() === linkedNodeId) || null;
          const registryState = String(node?.registry_state || node?.trust_status || "").toLowerCase();
          if (registryState === "trusted") return;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
    throw new Error("approval_finalize_timeout");
  }

  async function decide(action: "approve" | "reject") {
    if (!session || actionBusy) return;
    setActionBusy(action);
    setActionError(null);
    setApprovalWaitMsg(null);
    if (action === "approve") {
      setPresenterState("working");
    }
    try {
      const suffix = query ? `?${query}` : "";
      const payload = action === "reject" ? { rejection_reason: "operator_rejected" } : undefined;
      const res = await fetch(
        `/api/system/nodes/onboarding/sessions/${encodeURIComponent(session.session_id)}/${action}${suffix}`,
        {
          method: "POST",
          credentials: "include",
          headers: payload ? { "Content-Type": "application/json" } : undefined,
          body: payload ? JSON.stringify(payload) : undefined,
        },
      );
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = typeof body?.detail === "string" ? body.detail : body?.detail?.error || `HTTP ${res.status}`;
        throw new Error(detail);
      }
      if (action === "approve") {
        setApprovalWaitMsg("Approval recorded. Waiting for node finalization...");
        await waitForApprovalFinalization(session.session_id);
        setPresenterState("success");
        await new Promise((resolve) => setTimeout(resolve, 650));
      }
      notifyParent(action, session.session_id);
      closeApprovalWindow();
    } catch (e: unknown) {
      setPresenterState("presenting");
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setActionBusy(null);
      setApprovalWaitMsg(null);
    }
  }

  if (!sid || !state) {
    return (
      <section className="onboard-page">
        <div className="onboard-shell">
          <div className="onboard-header">
            <div className="onboard-eyebrow">Node Registration Approval</div>
            <p className="onboard-lead">Approved nodes receive trust material and operational MQTT credentials.</p>
          </div>
          <div className="onboard-error">Missing required `sid` or `state` in URL.</div>
        </div>
      </section>
    );
  }

  const canDecide = currentState === "pending" && actionBusy === null;

  return (
    <section className="onboard-page">
      <div className="onboard-shell">
        <div className="onboard-header">
          <div className="onboard-eyebrow">Node Registration Approval</div>
          <p className="onboard-lead">Approved nodes receive trust material and operational MQTT credentials.</p>
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
                  <h2 className="onboard-card-title">Core approval access</h2>
                </div>
                <div className="onboard-state-pill">Pending</div>
              </div>
              <div className="onboard-help">Sign in as Core admin to review and decide this onboarding request.</div>
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
                <div className="onboard-card-kicker">{presenter.eyebrow}</div>
                <h2 className="onboard-presenter-title">{presenter.title}</h2>
                <p className="onboard-lead onboard-presenter-lead">{presenter.copy}</p>
              </div>
              <div className="onboard-presenter-frame">
                <img className="onboard-presenter-image" src={presenter.image} alt={presenter.alt} />
              </div>
            </aside>
          </div>
        ) : loading ? (
          <div className="onboard-status-card">
            <div className="onboard-meta">Loading onboarding session...</div>
          </div>
        ) : error ? (
          <div className="onboard-error">{error}</div>
        ) : !session ? (
          <div className="onboard-error">Session not found.</div>
        ) : (
          <div className="onboard-approval-layout">
            <article className="onboard-card">
              <div className="onboard-card-top">
                <div>
                  <div className="onboard-card-kicker">Node Approval</div>
                  <h2 className="onboard-card-title">{session.node_name || session.requested_node_name}</h2>
                  <div className="onboard-meta">Review identity, session details, and connection source before granting trust.</div>
                </div>
                <div className={`onboard-state-pill onboard-state-pill-${currentState || "unknown"}`}>
                  {sessionStateLabel(session.session_state)}
                </div>
              </div>

              <div className="onboard-card-sections">
                <section className="onboard-section">
                  <div className="onboard-section-title">Identity</div>
                  <div className="onboard-field-grid">
                    <div className="onboard-field">
                      <strong>Node Name</strong>
                      <span>{session.node_name || session.requested_node_name}</span>
                    </div>
                    <div className="onboard-field">
                      <strong>Node Type</strong>
                      <span>{session.node_type || session.requested_node_type}</span>
                    </div>
                    <div className="onboard-field">
                      <strong>Version</strong>
                      <span>{session.node_software_version || session.requested_node_software_version}</span>
                    </div>
                    <div className="onboard-field">
                      <strong>Hostname</strong>
                      <span>{session.requested_hostname || "-"}</span>
                    </div>
                  </div>
                </section>

                <section className="onboard-section">
                  <div className="onboard-section-title">Session</div>
                  <div className="onboard-field-grid">
                    <div className="onboard-field">
                      <strong>Session ID</strong>
                      <span>{maskSessionId(session.session_id)}</span>
                    </div>
                    <div className="onboard-field">
                      <strong>Status</strong>
                      <span>{sessionStateLabel(session.session_state)}</span>
                    </div>
                    <div className="onboard-field">
                      <strong>Created At</strong>
                      <span>{fmt(session.created_at)}</span>
                    </div>
                    <div className="onboard-field">
                      <strong>Expires At</strong>
                      <span>{fmt(session.expires_at)}</span>
                    </div>
                  </div>
                </section>

                <section className="onboard-section">
                  <div className="onboard-section-title">Connection</div>
                  <div className="onboard-field-grid onboard-field-grid-connection">
                    <div className="onboard-field">
                      <strong>IP Address</strong>
                      <span>{session.requested_from_ip || "-"}</span>
                    </div>
                  </div>
                </section>
              </div>

              <div className="onboard-actions">
                <button
                  className="addon-btn addon-btn-primary onboard-action-primary"
                  type="button"
                  disabled={!canDecide}
                  onClick={() => void decide("approve")}
                >
                  {actionBusy === "approve" ? approvalWaitMsg || "Approving..." : "Approve"}
                </button>
                <button
                  className="addon-btn addon-btn-danger onboard-action-secondary"
                  type="button"
                  disabled={!canDecide}
                  onClick={() => void decide("reject")}
                >
                  {actionBusy === "reject" ? "Rejecting..." : "Reject"}
                </button>
              </div>

              {approvalWaitMsg && actionBusy === "approve" && <div className="onboard-meta">{approvalWaitMsg}</div>}
              {actionError && <div className="onboard-error">{actionError}</div>}
            </article>

            <aside className="onboard-presenter-panel">
              <div className="onboard-presenter-copy">
                <div className="onboard-card-kicker">{presenter.eyebrow}</div>
                <h2 className="onboard-presenter-title">{presenter.title}</h2>
                <p className="onboard-lead onboard-presenter-lead">{presenter.copy}</p>
                {presenterState === "success" && (
                  <div className="onboard-success-note">Approval complete. Closing this checkpoint now.</div>
                )}
              </div>
              <div className="onboard-presenter-frame">
                <img className="onboard-presenter-image" src={presenter.image} alt={presenter.alt} />
              </div>
            </aside>
          </div>
        )}
      </div>
    </section>
  );
}

import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

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

function fmt(ts?: string | null): string {
  if (!ts) return "-";
  const n = Date.parse(ts);
  if (!Number.isFinite(n)) return ts;
  return new Date(n).toLocaleString();
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

  const query = useMemo(() => {
    const q = new URLSearchParams();
    if (state) q.set("state", state);
    return q.toString();
  }, [state]);

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
    // If browser blocks self-close, navigate to a lightweight terminal route.
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

  async function decide(action: "approve" | "reject") {
    if (!session || actionBusy) return;
    setActionBusy(action);
    setActionError(null);
    setApprovalWaitMsg(null);
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
      }
      notifyParent(action, session.session_id);
      closeApprovalWindow();
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setActionBusy(null);
      setApprovalWaitMsg(null);
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
        const nodeRes = await fetch(`/api/system/nodes/registry`, {
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

  if (!sid || !state) {
    return (
      <section className="onboard-page">
        <h1>Node Registration Approval</h1>
        <div className="onboard-error">Missing required `sid` or `state` in URL.</div>
      </section>
    );
  }

  return (
    <section className="onboard-page">
      <h1>Node Registration Approval</h1>
      {!ready ? (
        <div className="onboard-meta">Checking admin session...</div>
      ) : !authenticated ? (
        <form className="onboard-login" onSubmit={submitLogin}>
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
          <button className="addon-btn" type="submit" disabled={loginBusy}>
            {loginBusy ? "Signing in..." : "Sign In"}
          </button>
          {loginErr && <div className="onboard-error">{loginErr}</div>}
        </form>
      ) : loading ? (
        <div className="onboard-meta">Loading onboarding session...</div>
      ) : error ? (
        <div className="onboard-error">{error}</div>
      ) : !session ? (
        <div className="onboard-error">Session not found.</div>
      ) : (
        <div className="onboard-card">
          <div className="onboard-row onboard-row-session">
            <div className="onboard-field">
              <strong>Session</strong>
              <span>{session.session_id}</span>
            </div>
          </div>
          <div className="onboard-row">
            <div className="onboard-field">
              <strong>State</strong>
              <span>{session.session_state}</span>
            </div>
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
          <div className="onboard-row">
            <div className="onboard-field">
              <strong>IP</strong>
              <span>{session.requested_from_ip || "-"}</span>
            </div>
            <div className="onboard-field">
              <strong>Created</strong>
              <span>{fmt(session.created_at)}</span>
            </div>
            <div className="onboard-field">
              <strong>Expires</strong>
              <span>{fmt(session.expires_at)}</span>
            </div>
          </div>
          <div className="onboard-actions">
            <button
              className="addon-btn"
              type="button"
              disabled={session.session_state !== "pending" || actionBusy !== null}
              onClick={() => void decide("approve")}
            >
              {actionBusy === "approve"
                ? approvalWaitMsg || "Approving..."
                : "Approve"}
            </button>
            <button
              className="addon-btn"
              type="button"
              disabled={session.session_state !== "pending" || actionBusy !== null}
              onClick={() => void decide("reject")}
            >
              {actionBusy === "reject" ? "Rejecting..." : "Reject"}
            </button>
          </div>
          {approvalWaitMsg && actionBusy === "approve" && <div className="onboard-meta">{approvalWaitMsg}</div>}
          {actionError && <div className="onboard-error">{actionError}</div>}
        </div>
      )}
    </section>
  );
}

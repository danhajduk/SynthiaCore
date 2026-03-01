import { useEffect, useMemo, useState } from "react";
import { apiGet } from "../api/client";
import "./addons.css";

type AddonInfo = {
  id: string;
  name: string;
  version: string;
  description: string;
  show_sidebar?: boolean;
  enabled?: boolean;
  base_url?: string | null;
  capabilities?: string[];
  health_status?: string;
  last_seen?: string | null;
  auth_mode?: string;
  tls_warning?: string | null;
  discovery_source?: string;
};

type RegistryAddon = {
  id: string;
  name: string;
  version: string;
  base_url: string;
  capabilities?: string[];
  health_status?: string;
  last_seen?: string | null;
};

type InstallSession = {
  session_id: string;
  addon_id: string;
  state: string;
  user_inputs: Record<string, unknown>;
  last_error: string | null;
  created_at: string;
  updated_at: string;
};

const POLLABLE_STATES = new Set(["pending_deployment", "discovered", "configured"]);

async function readError(res: Response): Promise<string> {
  const text = await res.text();
  return text || `HTTP ${res.status}`;
}

export default function Addons() {
  const [addons, setAddons] = useState<AddonInfo[]>([]);
  const [registryAddons, setRegistryAddons] = useState<RegistryAddon[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [wizardErr, setWizardErr] = useState<string | null>(null);
  const [wizardBusy, setWizardBusy] = useState<string | null>(null);
  const [selectedAddonId, setSelectedAddonId] = useState("");
  const [sessionIdInput, setSessionIdInput] = useState("");
  const [session, setSession] = useState<InstallSession | null>(null);
  const [deployMode, setDeployMode] = useState<"external" | "embedded">("external");
  const [brokerHost, setBrokerHost] = useState("10.0.0.100");
  const [brokerPort, setBrokerPort] = useState("1883");
  const [brokerTls, setBrokerTls] = useState(false);
  const [brokerUsername, setBrokerUsername] = useState("");
  const [brokerPassword, setBrokerPassword] = useState("");

  useEffect(() => {
    apiGet<AddonInfo[]>("/api/addons")
      .then(setAddons)
      .catch((e) => setErr(String(e)));
    apiGet<RegistryAddon[]>("/api/addons/registry")
      .then((items) => {
        setRegistryAddons(items);
        if (items.length > 0) {
          setSelectedAddonId((prev) => prev || items[0].id);
        }
      })
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    if (!session || !POLLABLE_STATES.has(session.state)) return;
    const timer = window.setInterval(() => {
      void refreshSession(session.session_id);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [session]);

  const selectedRegistryAddon = useMemo(
    () => registryAddons.find((x) => x.id === selectedAddonId) || null,
    [registryAddons, selectedAddonId],
  );

  async function setEnabled(addonId: string, enabled: boolean) {
    setErr(null);
    setBusy(addonId);
    try {
      const res = await fetch(`/api/addons/${addonId}/enable`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setAddons((prev) =>
        prev.map((a) => (a.id === addonId ? { ...a, enabled: data.enabled } : a))
      );
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function refreshSession(sessionId: string) {
    try {
      const res = await fetch(`/api/addons/install/${encodeURIComponent(sessionId)}`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error(await readError(res));
      const payload = (await res.json()) as { session?: InstallSession };
      if (payload.session) {
        setSession(payload.session);
        setSessionIdInput(payload.session.session_id);
      }
    } catch (e: any) {
      setWizardErr(e?.message ?? String(e));
    }
  }

  async function startInstall(addonId: string) {
    setWizardErr(null);
    setWizardBusy("start");
    try {
      const res = await fetch("/api/addons/install/start", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ addon_id: addonId }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const payload = (await res.json()) as { session?: InstallSession };
      if (!payload.session) throw new Error("install_session_missing");
      setSession(payload.session);
      setSessionIdInput(payload.session.session_id);
    } catch (e: any) {
      setWizardErr(e?.message ?? String(e));
    } finally {
      setWizardBusy(null);
    }
  }

  async function approvePermissions() {
    if (!session) return;
    setWizardErr(null);
    setWizardBusy("approve");
    try {
      const res = await fetch(`/api/addons/install/${encodeURIComponent(session.session_id)}/permissions/approve`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error(await readError(res));
      const payload = (await res.json()) as { session?: InstallSession };
      if (payload.session) setSession(payload.session);
    } catch (e: any) {
      setWizardErr(e?.message ?? String(e));
    } finally {
      setWizardBusy(null);
    }
  }

  async function selectDeployment() {
    if (!session) return;
    setWizardErr(null);
    setWizardBusy("deploy");
    try {
      const res = await fetch(`/api/addons/install/${encodeURIComponent(session.session_id)}/deployment/select`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: deployMode }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const payload = (await res.json()) as { session?: InstallSession };
      if (payload.session) setSession(payload.session);
    } catch (e: any) {
      setWizardErr(e?.message ?? String(e));
    } finally {
      setWizardBusy(null);
    }
  }

  async function configureAddon() {
    if (!session) return;
    setWizardErr(null);
    setWizardBusy("configure");
    try {
      const config = {
        broker_host: brokerHost.trim(),
        broker_port: Number(brokerPort || "1883"),
        broker_tls: brokerTls,
        broker_username: brokerUsername.trim() || null,
        broker_password: brokerPassword || null,
      };
      const res = await fetch(`/api/addons/install/${encodeURIComponent(session.session_id)}/configure`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const payload = (await res.json()) as { session?: InstallSession };
      if (payload.session) setSession(payload.session);
    } catch (e: any) {
      setWizardErr(e?.message ?? String(e));
    } finally {
      setWizardBusy(null);
    }
  }

  async function verifyAddon() {
    if (!session) return;
    setWizardErr(null);
    setWizardBusy("verify");
    try {
      const res = await fetch(`/api/addons/install/${encodeURIComponent(session.session_id)}/verify`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error(await readError(res));
      const payload = (await res.json()) as { session?: InstallSession };
      if (payload.session) setSession(payload.session);
      const registry = await apiGet<RegistryAddon[]>("/api/addons/registry");
      setRegistryAddons(registry);
    } catch (e: any) {
      setWizardErr(e?.message ?? String(e));
    } finally {
      setWizardBusy(null);
    }
  }

  return (
    <div>
      <h1 className="addons-title">Addons</h1>
      {err && <pre className="addons-error">{err}</pre>}
      {!err && (
        <div className="addons-container">
          <div className="addons-list">
          {addons.length === 0 ? (
            <div className="addons-empty">No backend addons loaded.</div>
          ) : (
            addons.map((a) => (
              <div
                key={a.id}
                className="addon-card"
              >
                <div className="addon-card-header">
                  <div className="addon-name">{a.name}</div>
                  <div className="addon-status">
                    {a.enabled === false ? "disabled" : "enabled"}
                  </div>
                </div>
                <div className="addon-meta">{a.id} • {a.version}</div>
                {a.base_url && <div className="addon-meta">base_url: {a.base_url}</div>}
                <div className="addon-meta">
                  health: {a.health_status ?? "unknown"}
                  {a.auth_mode ? ` • auth: ${a.auth_mode}` : ""}
                  {a.discovery_source ? ` • source: ${a.discovery_source}` : ""}
                </div>
                {a.last_seen && (
                  <div className="addon-meta">last seen: {new Date(a.last_seen).toLocaleString()}</div>
                )}
                {a.capabilities && a.capabilities.length > 0 && (
                  <div className="addon-desc">capabilities: {a.capabilities.join(", ")}</div>
                )}
                {a.tls_warning && <div className="addons-error">{a.tls_warning}</div>}
                {a.description && <div className="addon-desc">{a.description}</div>}
                <div className="addon-actions">
                  <button
                    onClick={() => setEnabled(a.id, !(a.enabled ?? true))}
                    disabled={busy === a.id}
                    className="addon-btn"
                  >
                    {a.enabled === false ? "Enable" : "Disable"}
                  </button>
                  <a
                    href={`/addons/${a.id}`}
                    className="addon-btn"
                  >
                    Open
                  </a>
                </div>
              </div>
            ))
          )}
          </div>
          <div className="addon-installer-card">
            <div className="addon-installer-title">Install Wizard</div>
            <div className="addon-meta">
              Start an install session, choose deployment mode, wait for discovery, then configure and verify.
            </div>
            {wizardErr && <pre className="addons-error">{wizardErr}</pre>}

            <label className="addon-input-label">
              Addon id
              <input
                className="addon-input"
                value={selectedAddonId}
                onChange={(e) => setSelectedAddonId(e.target.value)}
                placeholder="mqtt"
              />
            </label>
            <div className="addon-inline">
              <button
                className="addon-btn"
                onClick={() => startInstall(selectedAddonId)}
                disabled={!selectedAddonId.trim() || wizardBusy === "start"}
              >
                {wizardBusy === "start" ? "Starting..." : "Start Install"}
              </button>
              <button
                className="addon-btn"
                onClick={() => {
                  if (selectedRegistryAddon) void startInstall(selectedRegistryAddon.id);
                }}
                disabled={!selectedRegistryAddon || wizardBusy === "start"}
              >
                Start Selected Registry Addon
              </button>
            </div>

            <label className="addon-input-label">
              Session id
              <input
                className="addon-input"
                value={sessionIdInput}
                onChange={(e) => setSessionIdInput(e.target.value)}
                placeholder="paste session id to resume"
              />
            </label>
            <div className="addon-inline">
              <button
                className="addon-btn"
                onClick={() => void refreshSession(sessionIdInput)}
                disabled={!sessionIdInput.trim()}
              >
                Load Session
              </button>
              <button
                className="addon-btn"
                onClick={() => {
                  void apiGet<RegistryAddon[]>("/api/addons/registry").then(setRegistryAddons).catch((e) => setWizardErr(String(e)));
                }}
              >
                Refresh Registry
              </button>
            </div>

            {!session ? (
              <div className="addon-meta">No active install session.</div>
            ) : (
              <div className="addon-install-body">
                <div className="addon-meta">session: {session.session_id}</div>
                <div className="addon-meta">addon: {session.addon_id}</div>
                <div className="addon-meta">state: {session.state}</div>
                {session.last_error && <div className="addons-error">last_error: {session.last_error}</div>}

                <div className="addon-step">
                  <div className="addon-step-title">1) Permissions</div>
                  <button
                    className="addon-btn"
                    onClick={approvePermissions}
                    disabled={session.state !== "pending_permissions" || wizardBusy === "approve"}
                  >
                    {wizardBusy === "approve" ? "Approving..." : "Approve Permissions"}
                  </button>
                </div>

                <div className="addon-step">
                  <div className="addon-step-title">2) Deployment</div>
                  <div className="addon-inline">
                    <label>
                      <input
                        type="radio"
                        checked={deployMode === "external"}
                        onChange={() => setDeployMode("external")}
                      />
                      external
                    </label>
                    <label>
                      <input
                        type="radio"
                        checked={deployMode === "embedded"}
                        onChange={() => setDeployMode("embedded")}
                      />
                      embedded
                    </label>
                  </div>
                  <div className="addon-code">
                    {deployMode === "external"
                      ? "docker compose up -d"
                      : "docker compose --profile embedded up -d"}
                  </div>
                  <button
                    className="addon-btn"
                    onClick={selectDeployment}
                    disabled={session.state !== "pending_deployment" || wizardBusy === "deploy"}
                  >
                    {wizardBusy === "deploy" ? "Saving..." : "Save Deployment Choice"}
                  </button>
                </div>

                <div className="addon-step">
                  <div className="addon-step-title">3) Discovery</div>
                  <div className="addon-meta">
                    Waiting for `synthia/addons/{session.addon_id}/announce` to advance to `discovered`.
                  </div>
                  <button className="addon-btn" onClick={() => void refreshSession(session.session_id)}>
                    Check Status
                  </button>
                </div>

                <div className="addon-step">
                  <div className="addon-step-title">4) Configure</div>
                  <label className="addon-input-label">
                    Broker host
                    <input className="addon-input" value={brokerHost} onChange={(e) => setBrokerHost(e.target.value)} />
                  </label>
                  <label className="addon-input-label">
                    Broker port
                    <input className="addon-input" value={brokerPort} onChange={(e) => setBrokerPort(e.target.value)} />
                  </label>
                  <label className="addon-input-label">
                    Broker username
                    <input className="addon-input" value={brokerUsername} onChange={(e) => setBrokerUsername(e.target.value)} />
                  </label>
                  <label className="addon-input-label">
                    Broker password
                    <input
                      className="addon-input"
                      type="password"
                      value={brokerPassword}
                      onChange={(e) => setBrokerPassword(e.target.value)}
                    />
                  </label>
                  <label className="addon-input-label addon-inline">
                    <input type="checkbox" checked={brokerTls} onChange={(e) => setBrokerTls(e.target.checked)} />
                    TLS enabled
                  </label>
                  <button
                    className="addon-btn"
                    onClick={configureAddon}
                    disabled={!["discovered", "registered", "configured"].includes(session.state) || wizardBusy === "configure"}
                  >
                    {wizardBusy === "configure" ? "Configuring..." : "Send Config"}
                  </button>
                </div>

                <div className="addon-step">
                  <div className="addon-step-title">5) Verify</div>
                  <button
                    className="addon-btn"
                    onClick={verifyAddon}
                    disabled={!["configured", "verified"].includes(session.state) || wizardBusy === "verify"}
                  >
                    {wizardBusy === "verify" ? "Verifying..." : "Verify Health"}
                  </button>
                </div>

                <div className="addon-step">
                  <div className="addon-step-title">6) Finish</div>
                  {selectedRegistryAddon?.base_url ? (
                    <a
                      className="addon-btn"
                      href={`${selectedRegistryAddon.base_url.replace(/\/$/, "")}/ui`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open Addon UI
                    </a>
                  ) : (
                    <div className="addon-meta">Addon base_url not available yet.</div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

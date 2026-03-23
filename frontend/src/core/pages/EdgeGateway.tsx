import { useEffect, useState } from "react";
import { usePlatformBranding } from "../branding";
import "./settings.css";

type EdgeIdentity = {
  core_id: string;
  core_name: string;
  platform_domain: string;
  public_hostname: string;
  public_ui_hostname: string;
  public_api_hostname: string;
};

type CloudflareSettings = {
  enabled: boolean;
  account_id?: string | null;
  zone_id?: string | null;
  api_token_configured?: boolean;
  tunnel_id?: string | null;
  tunnel_name?: string | null;
  tunnel_token_ref?: string | null;
  credentials_reference?: string | null;
  public_dns_record_id?: string | null;
  ui_dns_record_id?: string | null;
  api_dns_record_id?: string | null;
  provisioning_state?: string;
  last_provisioned_at?: string | null;
  last_provision_error?: string | null;
  managed_domain_base: string;
  hostname_publication_mode: string;
};

type ProvisioningState = {
  overall_state: string;
  tunnel_state: string;
  public_hostname_state: string;
  ui_hostname_state: string;
  api_hostname_state: string;
  dns_state: string;
  runtime_config_state: string;
  last_action?: string | null;
  last_success_at?: string | null;
  last_error?: string | null;
  tunnel_id?: string | null;
  tunnel_name?: string | null;
  public_dns_record_id?: string | null;
  ui_dns_record_id?: string | null;
  api_dns_record_id?: string | null;
};

type EdgePublication = {
  publication_id: string;
  hostname: string;
  path_prefix: string;
  enabled: boolean;
  source: string;
  target: {
    target_type: string;
    target_id: string;
    upstream_base_url: string;
  };
};

type EdgeStatus = {
  public_identity: EdgeIdentity;
  cloudflare: CloudflareSettings;
  tunnel: {
    configured: boolean;
    runtime_state: string;
    healthy: boolean;
    tunnel_id?: string | null;
    tunnel_name?: string | null;
    config_path?: string | null;
    last_error?: string | null;
  };
  provisioning: ProvisioningState;
  publications: EdgePublication[];
  reconcile_state: Record<string, unknown>;
  validation_errors: string[];
};

const EMPTY_SETTINGS: CloudflareSettings = {
  enabled: false,
  tunnel_id: "",
  tunnel_name: "",
  tunnel_token_ref: "",
  credentials_reference: "",
  managed_domain_base: "hexe-ai.com",
  hostname_publication_mode: "core_id_managed",
};

export default function EdgeGateway() {
  const branding = usePlatformBranding();
  const [status, setStatus] = useState<EdgeStatus | null>(null);
  const [settings, setSettings] = useState<CloudflareSettings>(EMPTY_SETTINGS);
  const [err, setErr] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [publicationForm, setPublicationForm] = useState({
    hostname: "",
    path_prefix: "/",
    target_type: "local_service",
    target_id: "",
    upstream_base_url: "http://127.0.0.1:8081",
  });

  function applyTargetTypeDefaults(targetType: string) {
    setPublicationForm((current) => {
      if (targetType === "frigate") {
        return {
          ...current,
          target_type: targetType,
          target_id: current.target_id.trim() ? current.target_id : "frigate",
          upstream_base_url: "http://127.0.0.1:5000",
        };
      }
      if (current.target_type === "frigate") {
        return {
          ...current,
          target_type: targetType,
          target_id: current.target_id === "frigate" ? "" : current.target_id,
          upstream_base_url:
            current.upstream_base_url === "http://127.0.0.1:5000" ? "http://127.0.0.1:8081" : current.upstream_base_url,
        };
      }
      return { ...current, target_type: targetType };
    });
  }

  async function load() {
    setErr(null);
    try {
      const [statusRes, settingsRes] = await Promise.all([
        fetch("/api/edge/status", { cache: "no-store" }),
        fetch("/api/edge/cloudflare/settings", { cache: "no-store" }),
      ]);
      if (!statusRes.ok) throw new Error(`status HTTP ${statusRes.status}`);
      if (!settingsRes.ok) throw new Error(`settings HTTP ${settingsRes.status}`);
      const statusPayload = (await statusRes.json()) as EdgeStatus;
      const settingsPayload = (await settingsRes.json()) as CloudflareSettings;
      setStatus(statusPayload);
      setSettings({ ...EMPTY_SETTINGS, ...settingsPayload });
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    }
  }

  async function saveSettings() {
    setBusy(true);
    setErr(null);
    setMessage(null);
    try {
      const res = await fetch("/api/edge/cloudflare/settings", {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (!res.ok) throw new Error(await describeResponseError("save", res));
      await load();
      setMessage("Cloudflare settings saved.");
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runAction(path: string, successMessage: string) {
    setBusy(true);
    setErr(null);
    setMessage(null);
    try {
      const res = await fetch(path, { method: "POST", credentials: "include" });
      if (!res.ok) throw new Error(await describeResponseError("action", res));
      const payload = await res.json().catch(() => null);
      await load();
      const detail =
        typeof payload?.ok === "boolean" && !payload.ok
          ? "Action reported an error."
          : successMessage;
      setMessage(detail);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  async function createPublication() {
    setBusy(true);
    setErr(null);
    setMessage(null);
    try {
      const res = await fetch("/api/edge/publications", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hostname: publicationForm.hostname,
          path_prefix: publicationForm.path_prefix,
          enabled: true,
          source: "operator_defined",
          target: {
            target_type: publicationForm.target_type,
            target_id: publicationForm.target_id,
            upstream_base_url: publicationForm.upstream_base_url,
            allowed_path_prefixes: [publicationForm.path_prefix],
          },
        }),
      });
      if (!res.ok) throw new Error(await describeResponseError("create", res));
      setPublicationForm({
        hostname: "",
        path_prefix: "/",
        target_type: "local_service",
        target_id: "",
        upstream_base_url: "http://127.0.0.1:8081",
      });
      await load();
      setMessage("Publication created.");
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  async function togglePublication(item: EdgePublication) {
    setBusy(true);
    setErr(null);
    setMessage(null);
    try {
      const res = await fetch(`/api/edge/publications/${encodeURIComponent(item.publication_id)}`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !item.enabled }),
      });
      if (!res.ok) throw new Error(await describeResponseError("patch", res));
      await load();
      setMessage(`Publication ${!item.enabled ? "enabled" : "disabled"}.`);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  async function deletePublication(publicationId: string) {
    setBusy(true);
    setErr(null);
    setMessage(null);
    try {
      const res = await fetch(`/api/edge/publications/${encodeURIComponent(publicationId)}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) throw new Error(await describeResponseError("delete", res));
      await load();
      setMessage("Publication deleted.");
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function describeResponseError(action: string, res: Response) {
    let detail = "";
    try {
      const payload = await res.json();
      if (typeof payload?.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore parse errors and fall back to status-only message.
    }
    return detail ? `${action} HTTP ${res.status}: ${detail}` : `${action} HTTP ${res.status}`;
  }

  return (
    <div className="settings-page">
      <h1 className="settings-title">Edge Gateway</h1>
      <p className="settings-page-subtitle">
        Public ingress for {branding.coreName} using a single platform-managed Cloudflare hostname with path-based Core routing.
      </p>
      <p className="settings-muted">
        Additional publications reuse the same managed Cloudflare tunnel; they add ingress rules and DNS, not separate tunnels.
      </p>
      {err && <div className="settings-error">Edge Gateway error: {err}</div>}
      {message && <div className="settings-success">{message}</div>}

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Public Identity</h2>
          <p>Stable Core identity and the single public hostname reserved for Core UI, API, node UI proxy, and addon UI proxy paths.</p>
        </div>
        <div className="settings-card">
          <div className="settings-kv-grid">
            <div className="settings-kv-item">
              <div className="settings-label-text">Core ID</div>
              <div className="settings-mono">{status?.public_identity.core_id || "loading"}</div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Public hostname</div>
              <div className="settings-mono">{status?.public_identity.public_hostname || status?.public_identity.public_ui_hostname || "loading"}</div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Reserved routes</div>
              <div className="settings-mono">/, /api/*, /nodes/proxy/*, /addons/proxy/*</div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Managed domain</div>
              <div className="settings-mono">{status?.public_identity.platform_domain || "hexe-ai.com"}</div>
            </div>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Cloudflare</h2>
          <p>Platform-managed Cloudflare configuration for the shared Hexe AI domain.</p>
        </div>
        <div className="settings-card">
          <div className="settings-form">
            <label className="settings-toggle">
              <input
                type="checkbox"
                checked={settings.enabled}
                onChange={(e) => setSettings((current) => ({ ...current, enabled: e.target.checked }))}
              />
              <span>Enable Cloudflare publication</span>
            </label>
            {["credentials_reference"].map((field) => (
              <label key={field} className="settings-label">
                <div className="settings-label-text">{field.replace(/_/g, " ")}</div>
                <input
                  value={String((settings as Record<string, unknown>)[field] || "")}
                  onChange={(e) => setSettings((current) => ({ ...current, [field]: e.target.value }))}
                  className="settings-input"
                />
              </label>
            ))}
            <div className="settings-kv-grid">
              <div className="settings-kv-item">
                <div className="settings-label-text">Token state</div>
                <span className="settings-pill">{settings.api_token_configured ? "Configured" : "Missing"}</span>
              </div>
              <div className="settings-kv-item">
                <div className="settings-label-text">Token source</div>
                <div className="settings-mono">env:CLOUDFLARE_API_TOKEN</div>
              </div>
              <div className="settings-kv-item">
                <div className="settings-label-text">Account source</div>
                <div className="settings-mono">env:CLOUDFLARE_ACCOUNT_ID</div>
              </div>
              <div className="settings-kv-item">
                <div className="settings-label-text">Zone source</div>
                <div className="settings-mono">env:CLOUDFLARE_ZONE_ID</div>
              </div>
              <div className="settings-kv-item">
                <div className="settings-label-text">Managed tunnel name</div>
                <div className="settings-mono">{status?.provisioning.tunnel_name || status?.tunnel.tunnel_name || "Will derive from core id"}</div>
              </div>
            </div>
            <label className="settings-label">
              <div className="settings-label-text">Managed domain base</div>
              <input
                value={settings.managed_domain_base}
                onChange={(e) => setSettings((current) => ({ ...current, managed_domain_base: e.target.value }))}
                className="settings-input"
              />
            </label>
            <div className="settings-row-actions">
              <button className="settings-btn" disabled={busy} onClick={saveSettings}>
                {busy ? "Saving..." : "Save Cloudflare settings"}
              </button>
              <button className="settings-btn secondary" disabled={busy} onClick={() => void runAction("/api/edge/cloudflare/test", "Dry-run completed.")}>
                Dry-run test
              </button>
              <button className="settings-btn secondary" disabled={busy} onClick={() => void runAction("/api/edge/cloudflare/provision", "Provisioning completed.")}>
                Provision
              </button>
              <button className="settings-btn secondary" disabled={busy} onClick={() => void runAction("/api/edge/reconcile", "Reconcile completed.")}>
                Reconcile
              </button>
            </div>
            <p className="settings-muted">
              V1 uses a single platform-managed Cloudflare owner and reads token, account, and zone from fixed backend env vars.
            </p>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Status</h2>
          <p>Current publication and tunnel state.</p>
        </div>
        <div className="settings-card">
          <div className="settings-kv-grid">
            <div className="settings-kv-item">
              <div className="settings-label-text">Provisioning state</div>
              <span className="settings-pill">{status?.provisioning.overall_state || "not_configured"}</span>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Tunnel runtime</div>
              <span className="settings-pill">{status?.tunnel.runtime_state || "unknown"}</span>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Validation errors</div>
              <div>{status?.validation_errors.length ? status.validation_errors.join(", ") : "None"}</div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Config path</div>
              <div className="settings-mono">{status?.tunnel.config_path || "Not written yet"}</div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Tunnel ID</div>
              <div className="settings-mono">{status?.provisioning.tunnel_id || status?.tunnel.tunnel_id || "Not provisioned"}</div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Public DNS record</div>
              <div className="settings-mono">{status?.provisioning.public_dns_record_id || status?.cloudflare.public_dns_record_id || "Not provisioned"}</div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Route ownership</div>
              <div>/ to port 80, /api/* + /nodes/proxy/* + /addons/proxy/* to port 9001</div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Last success</div>
              <div>{status?.provisioning.last_success_at || status?.cloudflare.last_provisioned_at || "Never"}</div>
            </div>
            <div className="settings-kv-item">
              <div className="settings-label-text">Last error</div>
              <div>{status?.provisioning.last_error || status?.cloudflare.last_provision_error || status?.tunnel.last_error || "None"}</div>
            </div>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Publications</h2>
          <p>Core reserves the main public hostname and its root API/node/addon paths. Extra publications must avoid those reserved Core paths.</p>
        </div>
        <div className="settings-card">
          <div className="settings-form">
            <label className="settings-label">
              <div className="settings-label-text">Hostname</div>
              <input
                value={publicationForm.hostname}
                onChange={(e) => setPublicationForm((current) => ({ ...current, hostname: e.target.value }))}
                className="settings-input"
                placeholder={`service.${status?.public_identity.core_id || "coreid"}.hexe-ai.com`}
              />
            </label>
            <label className="settings-label">
              <div className="settings-label-text">Path prefix</div>
              <input
                value={publicationForm.path_prefix}
                onChange={(e) => setPublicationForm((current) => ({ ...current, path_prefix: e.target.value }))}
                className="settings-input"
              />
            </label>
            <label className="settings-label">
              <div className="settings-label-text">Target type</div>
              <select
                value={publicationForm.target_type}
                onChange={(e) => applyTargetTypeDefaults(e.target.value)}
                className="settings-select-input"
              >
                <option value="local_service">Local service</option>
                <option value="frigate">Frigate</option>
                <option value="supervisor_runtime">Supervisor runtime</option>
                <option value="node">Node</option>
              </select>
            </label>
            <label className="settings-label">
              <div className="settings-label-text">Target id</div>
              <input
                value={publicationForm.target_id}
                onChange={(e) => setPublicationForm((current) => ({ ...current, target_id: e.target.value }))}
                className="settings-input"
              />
            </label>
            <label className="settings-label">
              <div className="settings-label-text">Upstream base URL</div>
              <input
                value={publicationForm.upstream_base_url}
                onChange={(e) => setPublicationForm((current) => ({ ...current, upstream_base_url: e.target.value }))}
                className="settings-input"
              />
            </label>
            <div className="settings-row-actions">
              <button className="settings-btn" disabled={busy} onClick={createPublication}>
                {busy ? "Working..." : "Create publication"}
              </button>
            </div>
          </div>
        </div>
        <div className="settings-card">
          <div className="settings-kv-grid">
            {(status?.publications || []).map((item) => (
              <div key={item.publication_id} className="settings-kv-item">
                <div className="settings-label-text">{item.publication_id}</div>
                <div className="settings-mono">{item.hostname}{item.path_prefix}</div>
                <div>{item.target.target_type} {"->"} {item.target.upstream_base_url}</div>
                <div className="settings-row-actions">
                  <button className="settings-btn secondary" disabled={busy || item.source === "core_owned"} onClick={() => void togglePublication(item)}>
                    {item.enabled ? "Disable" : "Enable"}
                  </button>
                  <button className="settings-btn secondary" disabled={busy || item.source === "core_owned"} onClick={() => void deletePublication(item.publication_id)}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

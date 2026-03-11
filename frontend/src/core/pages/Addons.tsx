import { useEffect, useMemo, useState } from "react";
import { apiGet } from "../api/client";
import { useAdminSession } from "../auth/AdminSessionContext";
import {
  canShowUninstallAction,
  confirmingUninstallState,
  idleUninstallState,
  uninstallFailureState,
  uninstallingState,
  uninstallSuccessState,
  type AddonRuntimeKind,
  type UninstallViewState,
} from "./addonsUninstall";
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

type StandaloneAddonRuntime = {
  addon_id: string;
  desired_state: string;
  runtime_state: string;
  active_version: string | null;
  target_version: string | null;
  container_name: string | null;
  container_status: string | null;
  running: boolean | null;
  restart_count: number | null;
  started_at: string | null;
  health_status: string;
  health_detail: string | null;
  published_ports: string[];
  network: string | null;
  last_error: string | null;
};

type NodeRegistration = {
  node_id: string;
  node_name?: string;
  node_type?: string;
  node_software_version?: string;
  trust_status?: string;
  registry_state?: string;
  approved_by_user_id?: string | null;
  source_onboarding_session_id?: string | null;
  updated_at?: string | null;
};

async function readError(res: Response): Promise<string> {
  const text = await res.text();
  return text || `HTTP ${res.status}`;
}

export default function Addons() {
  const { authenticated: isAdmin } = useAdminSession();
  const [addons, setAddons] = useState<AddonInfo[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [runtimeItems, setRuntimeItems] = useState<StandaloneAddonRuntime[]>([]);
  const [runtimeErr, setRuntimeErr] = useState<string | null>(null);
  const [runtimeBusy, setRuntimeBusy] = useState(false);
  const [nodes, setNodes] = useState<NodeRegistration[]>([]);
  const [nodesErr, setNodesErr] = useState<string | null>(null);
  const [nodesBusy, setNodesBusy] = useState(false);
  const [nodeDeleteBusy, setNodeDeleteBusy] = useState<string | null>(null);
  const [nodesTab, setNodesTab] = useState<"installed" | "pending">("installed");
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [catalogMsg, setCatalogMsg] = useState<string | null>(null);
  const [uninstallStates, setUninstallStates] = useState<Record<string, UninstallViewState>>({});

  function uninstallStateFor(addonId: string): UninstallViewState {
    return uninstallStates[addonId] ?? idleUninstallState();
  }

  function setUninstallState(addonId: string, state: UninstallViewState) {
    setUninstallStates((prev) => ({ ...prev, [addonId]: state }));
  }

  function runtimeKindFor(addonId: string): AddonRuntimeKind {
    return runtimeItems.some((item) => item.addon_id === addonId) ? "standalone" : "embedded";
  }

  async function refreshInventory() {
    const addonsPayload = await apiGet<AddonInfo[]>("/api/addons");
    setAddons(addonsPayload);
  }

  async function refreshRuntime() {
    setRuntimeBusy(true);
    setRuntimeErr(null);
    try {
      const res = await fetch("/api/system/addons/runtime", {
        credentials: "include",
      });
      if (!res.ok) throw new Error(await readError(res));
      const payload = (await res.json()) as { items?: StandaloneAddonRuntime[] };
      setRuntimeItems(Array.isArray(payload.items) ? payload.items : []);
    } catch (e: any) {
      setRuntimeErr(e?.message ?? String(e));
    } finally {
      setRuntimeBusy(false);
    }
  }

  async function refreshNodes() {
    setNodesBusy(true);
    setNodesErr(null);
    try {
      const res = await fetch("/api/system/nodes/registry", {
        credentials: "include",
        cache: "no-store",
      });
      if (!res.ok) throw new Error(await readError(res));
      const payload = (await res.json()) as { items?: NodeRegistration[] };
      const items = Array.isArray(payload.items) ? payload.items : [];
      setNodes(items.sort((a, b) => String(a.node_id || "").localeCompare(String(b.node_id || ""))));
    } catch (e: any) {
      setNodesErr(e?.message ?? String(e));
      setNodes([]);
    } finally {
      setNodesBusy(false);
    }
  }

  async function updateCatalogNow() {
    setCatalogBusy(true);
    setCatalogMsg(null);
    try {
      const res = await fetch("/api/store/sources/official/refresh", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) throw new Error(await readError(res));
      setCatalogMsg("Catalog updated.");
    } catch (e: any) {
      setCatalogMsg(`Catalog update failed: ${e?.message ?? String(e)}`);
    } finally {
      setCatalogBusy(false);
    }
  }

  async function deleteNode(nodeId: string) {
    const target = String(nodeId || "").trim();
    if (!target) return;
    setNodesErr(null);
    setNodeDeleteBusy(target);
    try {
      const res = await fetch(`/api/system/nodes/registrations/${encodeURIComponent(target)}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) throw new Error(await readError(res));
      await refreshNodes();
    } catch (e: any) {
      setNodesErr(e?.message ?? String(e));
    } finally {
      setNodeDeleteBusy(null);
    }
  }

  useEffect(() => {
    refreshInventory()
      .catch((e) => setErr(String(e)));
    void refreshRuntime();
    void refreshNodes();
  }, []);

  const trustedNodes = useMemo(
    () => nodes.filter((item) => String(item.registry_state || item.trust_status || "").toLowerCase() === "trusted"),
    [nodes],
  );
  const pendingNodes = useMemo(
    () => nodes.filter((item) => String(item.registry_state || item.trust_status || "").toLowerCase() !== "trusted"),
    [nodes],
  );
  const visibleNodes = nodesTab === "installed" ? trustedNodes : pendingNodes;

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

  async function uninstallAddon(addonId: string) {
    setErr(null);
    setUninstallState(addonId, uninstallingState());
    const runtimeKind = runtimeKindFor(addonId);
    try {
      const res = await fetch("/api/store/uninstall", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ addon_id: addonId }),
      });
      if (!res.ok) {
        const raw = await readError(res);
        setUninstallState(addonId, uninstallFailureState(res.status, raw, runtimeKind));
        return;
      }
      setUninstallState(addonId, uninstallSuccessState());
      await refreshInventory();
      await refreshRuntime();
    } catch (e: any) {
      setUninstallState(addonId, uninstallFailureState(0, e?.message ?? String(e), runtimeKind));
    }
  }

  return (
    <div>
      <div className="addons-head">
        <h1 className="addons-title">Addons</h1>
        <div className="addons-head-actions">
          <button className="addon-btn" onClick={() => void updateCatalogNow()} disabled={catalogBusy}>
            {catalogBusy ? "Updating Catalog..." : "Update Catalog"}
          </button>
          <button className="addon-btn" onClick={() => void refreshInventory()} disabled={busy !== null}>
            Refresh List
          </button>
          <button className="addon-btn" onClick={() => void refreshNodes()} disabled={nodesBusy}>
            {nodesBusy ? "Refreshing Nodes..." : "Refresh Nodes"}
          </button>
        </div>
      </div>
      {catalogMsg && <div className="addon-meta">{catalogMsg}</div>}
      {err && <pre className="addons-error">{err}</pre>}
      {!err && (
        <div className="addons-list">
          {addons.length === 0 ? (
            <div className="addons-empty">No backend addons loaded.</div>
          ) : (
            addons.map((a) => {
              const uninstallState = uninstallStateFor(a.id);
              const disableCardActions = uninstallState.phase === "uninstalling";
              return (
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
                    disabled={busy === a.id || disableCardActions}
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
                  {canShowUninstallAction(isAdmin) && uninstallState.phase !== "confirming" && (
                    <button
                      onClick={() => setUninstallState(a.id, confirmingUninstallState())}
                      disabled={disableCardActions}
                      className="addon-btn addon-btn-danger"
                    >
                      {uninstallState.phase === "uninstalling" ? "Uninstalling..." : "Uninstall"}
                    </button>
                  )}
                  {canShowUninstallAction(isAdmin) && uninstallState.phase === "confirming" && (
                    <>
                      <button
                        onClick={() => void uninstallAddon(a.id)}
                        disabled={disableCardActions}
                        className="addon-btn addon-btn-danger"
                      >
                        Confirm Uninstall
                      </button>
                      <button
                        onClick={() => setUninstallState(a.id, idleUninstallState())}
                        disabled={disableCardActions}
                        className="addon-btn"
                      >
                        Cancel
                      </button>
                    </>
                  )}
                </div>
                {uninstallState.phase === "confirming" && (
                  <div className="addon-uninstall-note">Confirm uninstall of {a.id}?</div>
                )}
                {uninstallState.message && (
                  <div className={uninstallState.phase === "failed" ? "addons-error" : "addon-uninstall-note"}>
                    {uninstallState.message}
                  </div>
                )}
                {uninstallState.remediation.length > 0 && (
                  <ul className="addon-uninstall-remediation">
                    {uninstallState.remediation.map((item) => (
                      <li key={`${a.id}-${item}`}>{item}</li>
                    ))}
                  </ul>
                )}
                </div>
              );
            })
          )}
            <div className="addon-runtime-panel">
              <div className="addon-runtime-header">
                <div className="addon-installer-title">Standalone Runtime</div>
                <button className="addon-btn" onClick={() => void refreshRuntime()} disabled={runtimeBusy}>
                  {runtimeBusy ? "Refreshing..." : "Refresh Runtime"}
                </button>
              </div>
              <div className="addon-meta">
                Runtime status for standalone-service addons managed by the supervisor (desired state + runtime state +
                container metadata). Embedded addons like MQTT are not listed here.
              </div>
              {runtimeErr && <pre className="addons-error">{runtimeErr}</pre>}
              {runtimeItems.length === 0 ? (
                <div className="addon-meta">No standalone runtime entries found.</div>
              ) : (
                <div className="addon-runtime-list">
                  {runtimeItems.map((item) => (
                    <div key={item.addon_id} className="addon-runtime-card">
                      <div className="addon-card-header">
                        <div className="addon-name">{item.addon_id}</div>
                        <div className="addon-status">runtime: {item.runtime_state}</div>
                      </div>
                      <div className="addon-meta">
                        desired state: {item.desired_state} • service health: {item.health_status}
                      </div>
                      <div className="addon-meta">
                        active: {item.active_version ?? "unknown"} • target: {item.target_version ?? "none"}
                      </div>
                      <div className="addon-meta">
                        container: {item.container_name ?? "none"} • status: {item.container_status ?? "unknown"}
                        {typeof item.running === "boolean" ? ` • running: ${item.running ? "yes" : "no"}` : ""}
                      </div>
                      <div className="addon-meta">
                        network: {item.network ?? "unknown"} • restarts: {item.restart_count ?? 0}
                      </div>
                      {item.published_ports.length > 0 && (
                        <div className="addon-desc">ports: {item.published_ports.join(", ")}</div>
                      )}
                      {item.health_detail && <div className="addon-desc">health detail: {item.health_detail}</div>}
                      {item.last_error && <div className="addons-error">last error: {item.last_error}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="addon-runtime-panel">
              <div className="addon-runtime-header">
                <div className="addon-installer-title">Installed Nodes</div>
                <div className="addon-inline">
                  <button
                    className={`addon-btn${nodesTab === "installed" ? " addon-tab-active" : ""}`}
                    onClick={() => setNodesTab("installed")}
                    type="button"
                  >
                    Installed ({trustedNodes.length})
                  </button>
                  <button
                    className={`addon-btn${nodesTab === "pending" ? " addon-tab-active" : ""}`}
                    onClick={() => setNodesTab("pending")}
                    type="button"
                  >
                    Pending ({pendingNodes.length})
                  </button>
                  <button className="addon-btn" onClick={() => void refreshNodes()} disabled={nodesBusy}>
                    {nodesBusy ? "Refreshing..." : "Refresh Nodes"}
                  </button>
                </div>
              </div>
              <div className="addon-meta">
                Registered nodes from global node onboarding and trust lifecycle.
              </div>
              {nodesErr && <pre className="addons-error">{nodesErr}</pre>}
              {visibleNodes.length === 0 ? (
                <div className="addon-meta">No registered nodes found.</div>
              ) : (
                <div className="addon-runtime-list">
                  {visibleNodes.map((item) => (
                    <div key={item.node_id} className="addon-runtime-card">
                      <div className="addon-card-header">
                        <div className="addon-name">{item.node_name || item.node_id}</div>
                        <div className="addon-status">state: {item.registry_state || item.trust_status || "unknown"}</div>
                      </div>
                      <div className="addon-meta">
                        node id: {item.node_id} • type: {item.node_type || "unknown"}
                      </div>
                      <div className="addon-meta">
                        version: {item.node_software_version || "unknown"} • approved by: {item.approved_by_user_id || "-"}
                      </div>
                      <div className="addon-meta">
                        session: {item.source_onboarding_session_id || "-"} • updated:{" "}
                        {item.updated_at ? new Date(item.updated_at).toLocaleString() : "-"}
                      </div>
                      {isAdmin && (
                        <div className="addon-actions">
                          <button
                            className="addon-btn addon-btn-danger"
                            onClick={() => void deleteNode(item.node_id)}
                            disabled={nodeDeleteBusy === item.node_id}
                          >
                            {nodeDeleteBusy === item.node_id ? "Removing..." : "Remove Node"}
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
        </div>
      )}
    </div>
  );
}

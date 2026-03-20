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
  declared_capabilities?: string[];
  enabled_providers?: string[];
  capability_profile_id?: string | null;
  capability_status?: string;
  capability_taxonomy?: {
    version?: string;
    categories?: Array<{
      category_id?: string;
      label?: string;
      items?: string[];
      item_count?: number;
    }>;
    activation?: {
      stage?: string;
      declaration_received?: boolean;
      profile_accepted?: boolean;
      governance_issued?: boolean;
      operational?: boolean;
    };
  };
  governance_sync_status?: string;
  operational_ready?: boolean;
  active_governance_version?: string | null;
  approved_by_user_id?: string | null;
  source_onboarding_session_id?: string | null;
  updated_at?: string | null;
};

type NodeBudgetDeclaration = {
  node_id?: string;
  currency?: string;
  compute_unit?: string;
  default_period?: string;
  supports_money_budget?: boolean;
  supports_compute_budget?: boolean;
  supports_customer_allocations?: boolean;
  supports_provider_allocations?: boolean;
  supported_providers?: string[];
  setup_requirements?: string[];
  suggested_money_limit?: number | null;
  suggested_compute_limit?: number | null;
};

type NodeBudgetConfig = {
  currency?: string;
  compute_unit?: string;
  period?: string;
  reset_policy?: string;
  enforcement_mode?: string;
  overcommit_enabled?: boolean;
  shared_customer_pool?: boolean;
  shared_provider_pool?: boolean;
  node_money_limit?: number | null;
  node_compute_limit?: number | null;
};

type NodeBudgetAllocation = {
  subject_id: string;
  money_limit?: number | null;
  compute_limit?: number | null;
};

type NodeBudgetBundle = {
  node_id: string;
  setup_status: string;
  declaration?: NodeBudgetDeclaration | null;
  node_budget?: NodeBudgetConfig | null;
  customer_allocations?: NodeBudgetAllocation[];
  provider_allocations?: NodeBudgetAllocation[];
};

type NodeBudgetDraft = {
  currency: string;
  computeUnit: string;
  period: string;
  resetPolicy: string;
  enforcementMode: string;
  overcommitEnabled: boolean;
  sharedCustomerPool: boolean;
  sharedProviderPool: boolean;
  nodeMoneyLimit: string;
  nodeComputeLimit: string;
  customerAllocationsJson: string;
  providerAllocationsJson: string;
};

type RoutingModelMetadata = {
  model_id: string;
  normalized_model_id: string;
  pricing?: Record<string, number>;
  latency_metrics?: Record<string, number>;
  node_available: boolean;
  source: string;
};

type RoutingProviderGroup = {
  provider: string;
  models: RoutingModelMetadata[];
};

type RoutingNodeGroup = {
  node_id: string;
  node_available: boolean;
  providers: RoutingProviderGroup[];
};

type LifecycleStep = {
  label: string;
  complete: boolean;
};

async function readError(res: Response): Promise<string> {
  const text = await res.text();
  if (res.status === 401) return "Admin login required";
  if (res.status === 403) return "Admin access required";
  return text || `HTTP ${res.status}`;
}

function displayText(value?: string | null, fallback = "Unknown"): string {
  const text = String(value || "").trim();
  return text || fallback;
}

function sentenceCase(value?: string | null, fallback = "Unknown"): string {
  const text = String(value || "").trim();
  if (!text) return fallback;
  return text
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "-";
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return value;
  return new Date(parsed).toLocaleString();
}

function addonStatusLabel(addon: AddonInfo): string {
  if (addon.enabled === false) return "Disabled";
  const health = String(addon.health_status || "").trim().toLowerCase();
  if (health === "healthy") return "Running";
  if (health) return sentenceCase(health);
  return "Enabled";
}

function addonSourceLabel(addon: AddonInfo): string {
  return sentenceCase(addon.discovery_source || "local");
}

function nodeLifecycle(item: NodeRegistration): LifecycleStep[] {
  const activation = item.capability_taxonomy?.activation;
  const trusted = String(item.registry_state || item.trust_status || "").trim().toLowerCase() === "trusted";
  const capabilitiesReady =
    Boolean(activation?.profile_accepted) ||
    Boolean(activation?.declaration_received) ||
    ["accepted", "declared"].includes(String(item.capability_status || "").trim().toLowerCase());
  const governanceReady =
    Boolean(activation?.governance_issued) || String(item.governance_sync_status || "").trim().toLowerCase() === "issued";
  const operational = Boolean(item.operational_ready) || Boolean(activation?.operational);
  return [
    { label: "Trust", complete: trusted },
    { label: "Capabilities", complete: capabilitiesReady },
    { label: "Governance", complete: governanceReady },
    { label: "Operational", complete: operational },
  ];
}

function providerCapabilities(item: NodeRegistration): string[] {
  const declared = Array.isArray(item.declared_capabilities)
    ? item.declared_capabilities.map((value) => String(value || "").trim()).filter(Boolean)
    : [];
  return Array.from(new Set(declared));
}

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function buildBudgetDraft(bundle?: NodeBudgetBundle | null): NodeBudgetDraft {
  const declaration: NodeBudgetDeclaration = bundle?.declaration || {};
  const config: NodeBudgetConfig = bundle?.node_budget || {};
  return {
    currency: String(config.currency || declaration.currency || "USD"),
    computeUnit: String(config.compute_unit || declaration.compute_unit || "cost_units"),
    period: String(config.period || declaration.default_period || "monthly"),
    resetPolicy: String(config.reset_policy || "calendar"),
    enforcementMode: String(config.enforcement_mode || "hard_stop"),
    overcommitEnabled: Boolean(config.overcommit_enabled),
    sharedCustomerPool: Boolean(config.shared_customer_pool),
    sharedProviderPool: Boolean(config.shared_provider_pool),
    nodeMoneyLimit:
      config.node_money_limit != null
        ? String(config.node_money_limit)
        : declaration.suggested_money_limit != null
          ? String(declaration.suggested_money_limit)
          : "",
    nodeComputeLimit:
      config.node_compute_limit != null
        ? String(config.node_compute_limit)
        : declaration.suggested_compute_limit != null
          ? String(declaration.suggested_compute_limit)
          : "",
    customerAllocationsJson: prettyJson(bundle?.customer_allocations || []),
    providerAllocationsJson: prettyJson(bundle?.provider_allocations || []),
  };
}

function parseAllocationsJson(raw: string): NodeBudgetAllocation[] {
  const text = String(raw || "").trim();
  if (!text) return [];
  const parsed = JSON.parse(text);
  if (!Array.isArray(parsed)) {
    throw new Error("Allocations JSON must be an array");
  }
  return parsed.map((item) => ({
    subject_id: String(item?.subject_id || "").trim(),
    money_limit: item?.money_limit === "" || item?.money_limit == null ? null : Number(item.money_limit),
    compute_limit: item?.compute_limit === "" || item?.compute_limit == null ? null : Number(item.compute_limit),
  }));
}

export default function Addons() {
  const { authenticated: isAdmin } = useAdminSession();
  const [addons, setAddons] = useState<AddonInfo[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [restartBusy, setRestartBusy] = useState<string | null>(null);
  const [runtimeItems, setRuntimeItems] = useState<StandaloneAddonRuntime[]>([]);
  const [nodes, setNodes] = useState<NodeRegistration[]>([]);
  const [nodesErr, setNodesErr] = useState<string | null>(null);
  const [nodesBusy, setNodesBusy] = useState(false);
  const [nodeDeleteBusy, setNodeDeleteBusy] = useState<string | null>(null);
  const [nodeRevokeBusy, setNodeRevokeBusy] = useState<string | null>(null);
  const [routingByNode, setRoutingByNode] = useState<Record<string, RoutingNodeGroup>>({});
  const [routingBusy, setRoutingBusy] = useState(false);
  const [budgetsByNode, setBudgetsByNode] = useState<Record<string, NodeBudgetBundle>>({});
  const [budgetDraftByNode, setBudgetDraftByNode] = useState<Record<string, NodeBudgetDraft>>({});
  const [budgetBusyNode, setBudgetBusyNode] = useState<string | null>(null);
  const [budgetMessageByNode, setBudgetMessageByNode] = useState<Record<string, string | null>>({});
  const [nodesTab, setNodesTab] = useState<"installed" | "pending">("installed");
  const [nodeTypeFilter, setNodeTypeFilter] = useState<string>("all");
  const [nodeCapabilityFilter, setNodeCapabilityFilter] = useState<string>("all");
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [catalogMsg, setCatalogMsg] = useState<string | null>(null);
  const [uninstallStates, setUninstallStates] = useState<Record<string, UninstallViewState>>({});
  const [expandedProviders, setExpandedProviders] = useState<Record<string, boolean>>({});

  function uninstallStateFor(addonId: string): UninstallViewState {
    return uninstallStates[addonId] ?? idleUninstallState();
  }

  function setUninstallState(addonId: string, state: UninstallViewState) {
    setUninstallStates((prev) => ({ ...prev, [addonId]: state }));
  }

  function runtimeKindFor(addonId: string): AddonRuntimeKind {
    return runtimeItems.some((item) => item.addon_id === addonId) ? "standalone" : "embedded";
  }

  function toggleProviderModels(key: string) {
    setExpandedProviders((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function refreshInventory() {
    const addonsPayload = await apiGet<AddonInfo[]>("/api/addons");
    setAddons(addonsPayload);
  }

  async function refreshRuntime() {
    try {
      const res = await fetch("/api/system/addons/runtime", {
        credentials: "include",
      });
      if (!res.ok) throw new Error(await readError(res));
      const payload = (await res.json()) as { items?: StandaloneAddonRuntime[] };
      setRuntimeItems(Array.isArray(payload.items) ? payload.items : []);
    } catch {
      setRuntimeItems([]);
    }
  }

  async function refreshNodes() {
    if (!isAdmin) {
      setNodes([]);
      setNodesErr(null);
      setNodesBusy(false);
      return;
    }
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

  async function refreshRoutingMetadata() {
    if (!isAdmin) {
      setRoutingByNode({});
      setRoutingBusy(false);
      return;
    }
    setRoutingBusy(true);
    try {
      const res = await fetch("/api/system/nodes/providers/routing-metadata", {
        credentials: "include",
        cache: "no-store",
      });
      if (!res.ok) throw new Error(await readError(res));
      const payload = (await res.json()) as { nodes?: RoutingNodeGroup[] };
      const items = Array.isArray(payload.nodes) ? payload.nodes : [];
      const mapped: Record<string, RoutingNodeGroup> = {};
      for (const item of items) {
        const key = String(item?.node_id || "").trim();
        if (!key) continue;
        mapped[key] = item;
      }
      setRoutingByNode(mapped);
    } catch (e: any) {
      setNodesErr(e?.message ?? String(e));
      setRoutingByNode({});
    } finally {
      setRoutingBusy(false);
    }
  }

  async function refreshBudgets() {
    if (!isAdmin) {
      setBudgetsByNode({});
      setBudgetDraftByNode({});
      return;
    }
    try {
      const res = await fetch("/api/system/nodes/budgets", {
        credentials: "include",
        cache: "no-store",
      });
      if (!res.ok) throw new Error(await readError(res));
      const payload = (await res.json()) as { items?: NodeBudgetBundle[] };
      const items = Array.isArray(payload.items) ? payload.items : [];
      const mapped: Record<string, NodeBudgetBundle> = {};
      const drafts: Record<string, NodeBudgetDraft> = {};
      for (const item of items) {
        const key = String(item?.node_id || "").trim();
        if (!key) continue;
        mapped[key] = item;
        drafts[key] = buildBudgetDraft(item);
      }
      setBudgetsByNode(mapped);
      setBudgetDraftByNode((prev) => ({ ...drafts, ...Object.fromEntries(Object.entries(prev).filter(([key]) => !(key in drafts))) }));
    } catch (e: any) {
      setNodesErr(e?.message ?? String(e));
      setBudgetsByNode({});
    }
  }

  async function refreshAll() {
    setErr(null);
    await Promise.all([
      refreshInventory().catch((e) => setErr(String(e))),
      refreshRuntime(),
      refreshNodes(),
      refreshRoutingMetadata(),
      refreshBudgets(),
    ]);
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
      await refreshRoutingMetadata();
      await refreshBudgets();
    } catch (e: any) {
      setNodesErr(e?.message ?? String(e));
    } finally {
      setNodeDeleteBusy(null);
    }
  }

  async function revokeNode(nodeId: string) {
    const target = String(nodeId || "").trim();
    if (!target) return;
    setNodesErr(null);
    setNodeRevokeBusy(target);
    try {
      const res = await fetch(`/api/system/nodes/registrations/${encodeURIComponent(target)}/revoke`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error(await readError(res));
      await refreshNodes();
      await refreshRoutingMetadata();
      await refreshBudgets();
    } catch (e: any) {
      setNodesErr(e?.message ?? String(e));
    } finally {
      setNodeRevokeBusy(null);
    }
  }

  function updateBudgetDraft(nodeId: string, patch: Partial<NodeBudgetDraft>) {
    setBudgetDraftByNode((prev) => ({
      ...prev,
      [nodeId]: { ...(prev[nodeId] || buildBudgetDraft(budgetsByNode[nodeId])), ...patch },
    }));
  }

  async function saveNodeBudget(nodeId: string) {
    const target = String(nodeId || "").trim();
    if (!target) return;
    const draft = budgetDraftByNode[target] || buildBudgetDraft(budgetsByNode[target]);
    setBudgetBusyNode(target);
    setBudgetMessageByNode((prev) => ({ ...prev, [target]: null }));
    try {
      const customer_allocations = parseAllocationsJson(draft.customerAllocationsJson).filter((item) => item.subject_id);
      const provider_allocations = parseAllocationsJson(draft.providerAllocationsJson).filter((item) => item.subject_id);
      const res = await fetch(`/api/system/nodes/budgets/${encodeURIComponent(target)}`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          node_budget: {
            currency: draft.currency,
            compute_unit: draft.computeUnit,
            period: draft.period,
            reset_policy: draft.resetPolicy,
            enforcement_mode: draft.enforcementMode,
            overcommit_enabled: draft.overcommitEnabled,
            shared_customer_pool: draft.sharedCustomerPool,
            shared_provider_pool: draft.sharedProviderPool,
            node_money_limit: draft.nodeMoneyLimit === "" ? null : Number(draft.nodeMoneyLimit),
            node_compute_limit: draft.nodeComputeLimit === "" ? null : Number(draft.nodeComputeLimit),
          },
          customer_allocations,
          provider_allocations,
        }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const payload = (await res.json()) as { budget?: NodeBudgetBundle };
      if (payload.budget?.node_id) {
        setBudgetsByNode((prev) => ({ ...prev, [payload.budget!.node_id]: payload.budget! }));
        setBudgetDraftByNode((prev) => ({ ...prev, [payload.budget!.node_id]: buildBudgetDraft(payload.budget) }));
      }
      setBudgetMessageByNode((prev) => ({ ...prev, [target]: "Budget configuration saved." }));
    } catch (e: any) {
      setBudgetMessageByNode((prev) => ({ ...prev, [target]: e?.message ?? String(e) }));
    } finally {
      setBudgetBusyNode(null);
    }
  }

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
      setAddons((prev) => prev.map((item) => (item.id === addonId ? { ...item, enabled: data.enabled } : item)));
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function restartAddon(addonId: string) {
    if (runtimeKindFor(addonId) !== "standalone") return;
    setErr(null);
    setRestartBusy(addonId);
    try {
      const res = await fetch(`/api/supervisor/nodes/${encodeURIComponent(addonId)}/restart`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error(await readError(res));
      await refreshRuntime();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setRestartBusy(null);
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

  useEffect(() => {
    void refreshAll();
  }, [isAdmin]);

  const sortedAddons = useMemo(
    () => [...addons].sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id))),
    [addons],
  );
  const trustedNodes = useMemo(
    () => nodes.filter((item) => String(item.registry_state || item.trust_status || "").toLowerCase() === "trusted"),
    [nodes],
  );
  const pendingNodes = useMemo(
    () => nodes.filter((item) => String(item.registry_state || item.trust_status || "").toLowerCase() !== "trusted"),
    [nodes],
  );
  const nodeTypeOptions = useMemo(
    () => Array.from(new Set(nodes.map((item) => String(item.node_type || "").trim()).filter(Boolean))).sort(),
    [nodes],
  );
  const nodeCapabilityOptions = useMemo(() => {
    const allCapabilities = nodes.flatMap((item) =>
      Array.isArray(item.declared_capabilities) ? item.declared_capabilities.map((value) => String(value || "").trim()) : [],
    );
    return Array.from(new Set(allCapabilities.filter(Boolean))).sort();
  }, [nodes]);
  const visibleNodes = useMemo(() => {
    const base = nodesTab === "installed" ? trustedNodes : pendingNodes;
    return base.filter((item) => {
      const typeMatch = nodeTypeFilter === "all" || String(item.node_type || "").trim() === nodeTypeFilter;
      const capabilities = Array.isArray(item.declared_capabilities) ? item.declared_capabilities : [];
      const capabilityMatch = nodeCapabilityFilter === "all" || capabilities.includes(nodeCapabilityFilter);
      return typeMatch && capabilityMatch;
    });
  }, [nodesTab, trustedNodes, pendingNodes, nodeTypeFilter, nodeCapabilityFilter]);

  return (
    <div className="addons-page">
      <div className="addons-head addons-hero">
        <div className="addons-hero-copy">
          <h1 className="addons-title">Addons &amp; Nodes</h1>
          <p className="addons-subtitle">Extensions that expand the Synthia platform.</p>
          <div className="addon-meta">Supervisor runtime details remain under System pages, not in this extension inventory.</div>
        </div>
        <div className="addons-head-actions">
          <button className="addon-btn" onClick={() => void updateCatalogNow()} disabled={catalogBusy}>
            {catalogBusy ? "Updating Catalog..." : "Update Catalog"}
          </button>
          <button className="addon-btn" onClick={() => void refreshAll()} disabled={nodesBusy || routingBusy || busy !== null}>
            {nodesBusy || routingBusy ? "Refreshing..." : "Refresh"}
          </button>
          <a className="addon-btn addon-btn-primary" href="/settings">
            Add Node
          </a>
        </div>
      </div>
      {catalogMsg && <div className="addon-meta">{catalogMsg}</div>}
      {err && <pre className="addons-error">{err}</pre>}

      <section className="addons-section">
        <div className="addons-section-head">
          <div>
            <h2 className="addons-section-title">Addons</h2>
            <div className="addon-meta">Platform extensions running inside Core or through supported standalone addon runtimes.</div>
          </div>
          <div className="addons-section-summary">
            <span className="addons-count">{sortedAddons.length} installed</span>
          </div>
        </div>
        {sortedAddons.length === 0 ? (
          <div className="addons-empty">No backend addons loaded.</div>
        ) : (
          <div className="addons-grid">
            {sortedAddons.map((addon) => {
              const uninstallState = uninstallStateFor(addon.id);
              const disableCardActions =
                uninstallState.phase === "uninstalling" || busy === addon.id || restartBusy === addon.id;
              const runtimeKind = runtimeKindFor(addon.id);
              const restartSupported = runtimeKind === "standalone";
              return (
                <article key={addon.id} className="inventory-card">
                  <div className="inventory-card-header">
                    <div>
                      <div className="addon-name">{addon.name}</div>
                      <div className="addon-meta">{addon.id}</div>
                    </div>
                    <div className="inventory-pill">{addonStatusLabel(addon)}</div>
                  </div>

                  <div className="inventory-detail-grid">
                    <div className="inventory-detail">
                      <span className="inventory-label">Version</span>
                      <span>{displayText(addon.version)}</span>
                    </div>
                    <div className="inventory-detail">
                      <span className="inventory-label">Source</span>
                      <span>{addonSourceLabel(addon)}</span>
                    </div>
                    <div className="inventory-detail">
                      <span className="inventory-label">Runtime</span>
                      <span>{sentenceCase(runtimeKind)}</span>
                    </div>
                    <div className="inventory-detail">
                      <span className="inventory-label">Last seen</span>
                      <span>{formatTimestamp(addon.last_seen)}</span>
                    </div>
                  </div>

                  {addon.capabilities && addon.capabilities.length > 0 && (
                    <div className="inventory-tag-list">
                      {addon.capabilities.map((capability) => (
                        <span key={`${addon.id}-${capability}`} className="inventory-tag">
                          {capability}
                        </span>
                      ))}
                    </div>
                  )}

                  {addon.description && <div className="addon-desc">{addon.description}</div>}
                  {addon.base_url && <div className="addon-meta">Base URL: {addon.base_url}</div>}
                  {addon.tls_warning && <div className="addons-error">{addon.tls_warning}</div>}

                  <div className="addon-actions">
                    <a href={`/addons/${addon.id}`} className="addon-btn">
                      Open
                    </a>
                    <button
                      onClick={() => void restartAddon(addon.id)}
                      disabled={!restartSupported || disableCardActions}
                      className="addon-btn"
                      title={restartSupported ? "Restart standalone addon runtime" : "Restart is not supported for this addon"}
                    >
                      {restartBusy === addon.id ? "Restarting..." : "Restart"}
                    </button>
                    <button
                      onClick={() => void setEnabled(addon.id, !(addon.enabled ?? true))}
                      disabled={disableCardActions}
                      className="addon-btn"
                    >
                      {addon.enabled === false ? "Enable" : "Disable"}
                    </button>
                    {canShowUninstallAction(isAdmin) && uninstallState.phase !== "confirming" && (
                      <button
                        onClick={() => setUninstallState(addon.id, confirmingUninstallState())}
                        disabled={disableCardActions}
                        className="addon-btn addon-btn-danger"
                      >
                        {uninstallState.phase === "uninstalling" ? "Uninstalling..." : "Uninstall"}
                      </button>
                    )}
                    {canShowUninstallAction(isAdmin) && uninstallState.phase === "confirming" && (
                      <>
                        <button
                          onClick={() => void uninstallAddon(addon.id)}
                          disabled={disableCardActions}
                          className="addon-btn addon-btn-danger"
                        >
                          Confirm Uninstall
                        </button>
                        <button
                          onClick={() => setUninstallState(addon.id, idleUninstallState())}
                          disabled={disableCardActions}
                          className="addon-btn"
                        >
                          Cancel
                        </button>
                      </>
                    )}
                  </div>

                  {uninstallState.phase === "confirming" && (
                    <div className="addon-uninstall-note">Confirm uninstall of {addon.id}?</div>
                  )}
                  {uninstallState.message && (
                    <div className={uninstallState.phase === "failed" ? "addons-error" : "addon-uninstall-note"}>
                      {uninstallState.message}
                    </div>
                  )}
                  {uninstallState.remediation.length > 0 && (
                    <ul className="addon-uninstall-remediation">
                      {uninstallState.remediation.map((item) => (
                        <li key={`${addon.id}-${item}`}>{item}</li>
                      ))}
                    </ul>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section className="addons-section">
        <div className="addons-section-head">
          <div>
            <h2 className="addons-section-title">Nodes</h2>
            <div className="addon-meta">Trusted external Synthia components with onboarding, governance, and provider status.</div>
          </div>
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
            <button
              className="addon-btn"
              onClick={() => {
                void refreshNodes();
                void refreshRoutingMetadata();
                void refreshBudgets();
              }}
              disabled={nodesBusy || routingBusy}
            >
              {nodesBusy || routingBusy ? "Refreshing..." : "Refresh Nodes"}
            </button>
            <label className="addon-input-label">
              Node type
              <select className="addon-input" value={nodeTypeFilter} onChange={(e) => setNodeTypeFilter(e.target.value)}>
                <option value="all">All</option>
                {nodeTypeOptions.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="addon-input-label">
              Capability
              <select
                className="addon-input"
                value={nodeCapabilityFilter}
                onChange={(e) => setNodeCapabilityFilter(e.target.value)}
              >
                <option value="all">All</option>
                {nodeCapabilityOptions.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {nodesErr && <pre className="addons-error">{nodesErr}</pre>}
        {visibleNodes.length === 0 ? (
          <div className="addons-empty">
            {nodesTab === "installed" ? "No installed nodes match the current filters." : "No pending nodes match the current filters."}
          </div>
        ) : (
          <div className="addons-grid">
            {visibleNodes.map((item) => {
              const routing = routingByNode[item.node_id];
              const budgetBundle = budgetsByNode[item.node_id];
              const budgetDraft = budgetDraftByNode[item.node_id] || buildBudgetDraft(budgetBundle);
              const budgetDeclaration = budgetBundle?.declaration;
              const budgetMessage = budgetMessageByNode[item.node_id];
              const stages = nodeLifecycle(item);
              const capabilityTags = providerCapabilities(item);
              const providers = routing?.providers ?? [];
              const totalModels = providers.reduce((sum, provider) => sum + provider.models.length, 0);
              return (
                <article key={item.node_id} className="inventory-card inventory-card-node">
                  <div className="inventory-card-header">
                    <div>
                      <div className="addon-name">{displayText(item.node_name, item.node_id)}</div>
                      <div className="addon-meta">{item.node_id}</div>
                    </div>
                    <div className="inventory-pill">{sentenceCase(item.registry_state || item.trust_status || "pending")}</div>
                  </div>

                  <div className="inventory-detail-grid">
                    <div className="inventory-detail">
                      <span className="inventory-label">Type</span>
                      <span>{displayText(item.node_type)}</span>
                    </div>
                    <div className="inventory-detail">
                      <span className="inventory-label">Lifecycle</span>
                      <span>{sentenceCase(item.capability_taxonomy?.activation?.stage || item.capability_status || "pending")}</span>
                    </div>
                    <div className="inventory-detail">
                      <span className="inventory-label">Trust</span>
                      <span>{sentenceCase(item.trust_status || item.registry_state || "pending")}</span>
                    </div>
                    <div className="inventory-detail">
                      <span className="inventory-label">Governance</span>
                      <span>{sentenceCase(item.governance_sync_status || "pending")}</span>
                    </div>
                  </div>

                  <div className="node-lifecycle">
                    {stages.map((stage) => (
                      <div
                        key={`${item.node_id}-${stage.label}`}
                        className={`node-lifecycle-step${stage.complete ? " node-lifecycle-step-complete" : ""}`}
                      >
                        <span className="node-lifecycle-icon">{stage.complete ? "✓" : "○"}</span>
                        <span>{stage.label}</span>
                      </div>
                    ))}
                  </div>

                  <div className="node-provider-summary">
                    <div className="node-provider-summary-head">
                      <div>
                        <div className="inventory-label">Providers</div>
                        <div className="addon-meta">
                          {providers.length > 0
                            ? `${providers.length} provider${providers.length === 1 ? "" : "s"} • ${totalModels} models detected`
                            : "No routing metadata reported yet"}
                        </div>
                      </div>
                      <div className="inventory-pill inventory-pill-subtle">
                        {routing?.node_available ? "Available" : "Pending"}
                      </div>
                    </div>

                    {capabilityTags.length > 0 && (
                      <div className="inventory-tag-list">
                        {capabilityTags.map((tag) => (
                          <span key={`${item.node_id}-${tag}`} className="inventory-tag">
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}

                    {providers.map((provider) => {
                      const toggleKey = `${item.node_id}:${provider.provider}`;
                      const expanded = Boolean(expandedProviders[toggleKey]);
                      const source = provider.models[0]?.source;
                      return (
                        <div key={toggleKey} className="provider-card">
                          <div className="provider-card-head">
                            <div>
                              <div className="provider-name">{sentenceCase(provider.provider)}</div>
                              <div className="addon-meta">
                                Models detected: {provider.models.length}
                                {source ? ` • source: ${source}` : ""}
                              </div>
                            </div>
                            <button className="addon-btn" type="button" onClick={() => toggleProviderModels(toggleKey)}>
                              {expanded ? "Hide Models" : "View Models"}
                            </button>
                          </div>
                          {expanded && (
                            <div className="provider-model-list">
                              {provider.models.map((model) => {
                                const pricing = Object.entries(model.pricing || {})
                                  .map(([key, value]) => `${key}=${value}`)
                                  .join(", ");
                                const latency = Object.entries(model.latency_metrics || {})
                                  .map(([key, value]) => `${key}=${value}ms`)
                                  .join(", ");
                                return (
                                  <div key={`${toggleKey}-${model.normalized_model_id}`} className="provider-model-item">
                                    <div className="provider-model-name">{model.model_id}</div>
                                    <div className="addon-meta">Latency: {latency || "-"}</div>
                                    <div className="addon-meta">Pricing: {pricing || "-"}</div>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  <div className="addon-meta">
                    Version: {displayText(item.node_software_version)} • Governance version: {displayText(item.active_governance_version, "-")}
                  </div>
                  <div className="addon-meta">
                    Onboarding session: {displayText(item.source_onboarding_session_id, "-")} • Updated: {formatTimestamp(item.updated_at)}
                  </div>

                  <div className="budget-card">
                    <div className="budget-card-head">
                      <div className="inventory-label">Budget Setup</div>
                      <div className="addon-meta">Status: {sentenceCase(budgetBundle?.setup_status || "not_declared")}</div>
                    </div>
                    <div className="addon-meta">
                      Declared: {budgetDeclaration ? "Yes" : "No"} • Currency: {displayText(budgetDeclaration?.currency, "USD")} • Compute unit: {displayText(budgetDeclaration?.compute_unit, "cost_units")}
                    </div>
                    {budgetDeclaration && (
                      <div className="addon-meta">
                        Customer allocations: {budgetDeclaration.supports_customer_allocations ? "Supported" : "Not supported"} • Provider allocations: {budgetDeclaration.supports_provider_allocations ? "Supported" : "Not supported"}
                      </div>
                    )}
                    {budgetDeclaration?.supported_providers?.length ? (
                      <div className="addon-meta">Declared providers: {budgetDeclaration.supported_providers.join(", ")}</div>
                    ) : null}
                    {budgetDeclaration?.setup_requirements?.length ? (
                      <div className="addon-meta">Setup requirements: {budgetDeclaration.setup_requirements.join(", ")}</div>
                    ) : null}
                    {budgetDeclaration ? (
                      <>
                        <div className="budget-grid">
                          <label className="budget-field">
                            <span className="inventory-label">Currency</span>
                            <input value={budgetDraft.currency} onChange={(e) => updateBudgetDraft(item.node_id, { currency: e.target.value })} />
                          </label>
                          <label className="budget-field">
                            <span className="inventory-label">Compute Unit</span>
                            <input value={budgetDraft.computeUnit} onChange={(e) => updateBudgetDraft(item.node_id, { computeUnit: e.target.value })} />
                          </label>
                          <label className="budget-field">
                            <span className="inventory-label">Period</span>
                            <input value={budgetDraft.period} onChange={(e) => updateBudgetDraft(item.node_id, { period: e.target.value })} />
                          </label>
                          <label className="budget-field">
                            <span className="inventory-label">Reset Policy</span>
                            <input value={budgetDraft.resetPolicy} onChange={(e) => updateBudgetDraft(item.node_id, { resetPolicy: e.target.value })} />
                          </label>
                          <label className="budget-field">
                            <span className="inventory-label">Money Limit</span>
                            <input value={budgetDraft.nodeMoneyLimit} onChange={(e) => updateBudgetDraft(item.node_id, { nodeMoneyLimit: e.target.value })} placeholder="10.0" />
                          </label>
                          <label className="budget-field">
                            <span className="inventory-label">Compute Limit</span>
                            <input value={budgetDraft.nodeComputeLimit} onChange={(e) => updateBudgetDraft(item.node_id, { nodeComputeLimit: e.target.value })} placeholder="100" />
                          </label>
                          <label className="budget-toggle">
                            <input type="checkbox" checked={budgetDraft.overcommitEnabled} onChange={(e) => updateBudgetDraft(item.node_id, { overcommitEnabled: e.target.checked })} />
                            <span>Allow overcommit</span>
                          </label>
                          <label className="budget-toggle">
                            <input type="checkbox" checked={budgetDraft.sharedCustomerPool} onChange={(e) => updateBudgetDraft(item.node_id, { sharedCustomerPool: e.target.checked })} />
                            <span>Shared customer pool</span>
                          </label>
                          <label className="budget-toggle">
                            <input type="checkbox" checked={budgetDraft.sharedProviderPool} onChange={(e) => updateBudgetDraft(item.node_id, { sharedProviderPool: e.target.checked })} />
                            <span>Shared provider pool</span>
                          </label>
                        </div>
                        {budgetDeclaration.supports_customer_allocations ? (
                          <label className="budget-field budget-field-wide">
                            <span className="inventory-label">Customer Allocations JSON</span>
                            <textarea
                              value={budgetDraft.customerAllocationsJson}
                              onChange={(e) => updateBudgetDraft(item.node_id, { customerAllocationsJson: e.target.value })}
                              rows={6}
                            />
                          </label>
                        ) : null}
                        {budgetDeclaration.supports_provider_allocations ? (
                          <label className="budget-field budget-field-wide">
                            <span className="inventory-label">Provider Allocations JSON</span>
                            <textarea
                              value={budgetDraft.providerAllocationsJson}
                              onChange={(e) => updateBudgetDraft(item.node_id, { providerAllocationsJson: e.target.value })}
                              rows={6}
                            />
                          </label>
                        ) : null}
                        {budgetMessage ? <div className="addon-meta">{budgetMessage}</div> : null}
                        <div className="addon-actions">
                          <button
                            className="addon-btn addon-btn-primary"
                            type="button"
                            onClick={() => void saveNodeBudget(item.node_id)}
                            disabled={budgetBusyNode === item.node_id}
                          >
                            {budgetBusyNode === item.node_id ? "Saving Budget..." : "Save Budget"}
                          </button>
                        </div>
                      </>
                    ) : (
                      <div className="addon-meta">This node has not declared budget capabilities yet, so Core cannot present a setup form.</div>
                    )}
                  </div>

                  <div className="addon-actions">
                    <a href={`/nodes/${encodeURIComponent(item.node_id)}`} className="addon-btn">
                      Open
                    </a>
                    <button
                      className="addon-btn"
                      type="button"
                      onClick={() => {
                        void refreshNodes();
                        void refreshRoutingMetadata();
                        void refreshBudgets();
                      }}
                      disabled={nodesBusy || routingBusy}
                    >
                      Refresh
                    </button>
                    <a
                      href={`/api/system/nodes/providers/routing-metadata?node_id=${encodeURIComponent(item.node_id)}`}
                      target="_blank"
                      rel="noreferrer"
                      className="addon-btn"
                    >
                      Diagnostics
                    </a>
                    {isAdmin && String(item.registry_state || item.trust_status || "").toLowerCase() !== "revoked" && (
                      <button
                        className="addon-btn addon-btn-danger"
                        onClick={() => void revokeNode(item.node_id)}
                        disabled={nodeRevokeBusy === item.node_id}
                      >
                        {nodeRevokeBusy === item.node_id ? "Revoking..." : "Revoke Trust"}
                      </button>
                    )}
                    {isAdmin && (
                      <button
                        className="addon-btn addon-btn-danger"
                        onClick={() => void deleteNode(item.node_id)}
                        disabled={nodeDeleteBusy === item.node_id}
                      >
                        {nodeDeleteBusy === item.node_id ? "Removing..." : "Remove Node"}
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

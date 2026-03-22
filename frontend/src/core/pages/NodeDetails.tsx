import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useAdminSession } from "../auth/AdminSessionContext";
import { usePlatformBranding } from "../branding";
import { nodeUiFrameSrc } from "./nodeFrameUrl";
import "./node-details.css";

type NodeCapabilityCategorySummary = {
  category_id: string;
  label: string;
  items: string[];
  item_count: number;
};

type NodeCapabilityActivationSummary = {
  stage: string;
  declaration_received: boolean;
  profile_accepted: boolean;
  governance_issued: boolean;
  operational: boolean;
};

type NodeCapabilityTaxonomySummary = {
  version: string;
  categories: NodeCapabilityCategorySummary[];
  activation: NodeCapabilityActivationSummary;
};

type NodeCapabilitySummary = {
  declared_capabilities: string[];
  enabled_providers: string[];
  capability_profile_id?: string | null;
  capability_status: string;
  capability_declaration_version?: string | null;
  capability_declaration_timestamp?: string | null;
  taxonomy: NodeCapabilityTaxonomySummary;
};

type NodeStatusSummary = {
  trust_status: string;
  registry_state: string;
  governance_sync_status: string;
  operational_ready: boolean;
  active_governance_version?: string | null;
  governance_last_issued_at?: string | null;
  governance_last_refresh_request_at?: string | null;
};

type ProviderModel = {
  model_id?: string;
  normalized_model_id?: string;
  pricing?: Record<string, number>;
  latency_metrics?: Record<string, number>;
};

type ProviderIntelligence = {
  provider?: string;
  available_models?: ProviderModel[];
};

type NodeRecord = {
  node_id: string;
  node_name: string;
  node_type: string;
  requested_node_type?: string | null;
  requested_hostname?: string | null;
  requested_ui_endpoint?: string | null;
  requested_api_base_url?: string | null;
  api_base_url?: string | null;
  node_software_version: string;
  approved_by_user_id?: string | null;
  approved_at?: string | null;
  source_onboarding_session_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  provider_intelligence: ProviderIntelligence[];
  capabilities: NodeCapabilitySummary;
  status: NodeStatusSummary;
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

function sentenceCase(value?: string | null, fallback = "Unknown"): string {
  const text = String(value || "").trim();
  if (!text) return fallback;
  return text.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "-";
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return value;
  return new Date(parsed).toLocaleString();
}

function providerTitle(value?: string | null): string {
  return sentenceCase(value, "Unknown provider");
}

function lifecycleSteps(node: NodeRecord): LifecycleStep[] {
  const activation = node.capabilities.taxonomy.activation;
  return [
    { label: "Trust", complete: node.status.trust_status === "trusted" || node.status.registry_state === "trusted" },
    { label: "Capabilities", complete: activation.profile_accepted || activation.declaration_received },
    { label: "Governance", complete: activation.governance_issued || node.status.governance_sync_status === "issued" },
    { label: "Operational", complete: activation.operational || node.status.operational_ready },
  ];
}

function formatMap(values?: Record<string, number>): string {
  const entries = Object.entries(values || {});
  if (entries.length === 0) return "-";
  return entries.map(([key, value]) => `${key}=${value}`).join(", ");
}

async function readError(res: Response): Promise<string> {
  try {
    const payload = await res.json();
    if (typeof payload?.detail === "string" && payload.detail.trim()) return payload.detail.trim();
    if (typeof payload?.error === "string" && payload.error.trim()) return payload.error.trim();
  } catch {
    // Ignore parse failures and fall back to status text.
  }
  return `HTTP ${res.status}`;
}

export default function NodeDetails() {
  const { authenticated: isAdmin } = useAdminSession();
  const branding = usePlatformBranding();
  const navigate = useNavigate();
  const { nodeId = "" } = useParams();
  const [node, setNode] = useState<NodeRecord | null>(null);
  const [routing, setRouting] = useState<RoutingNodeGroup | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [nodeRes, routingRes] = await Promise.all([
          fetch(`/api/nodes/${encodeURIComponent(nodeId)}`, { credentials: "include", cache: "no-store" }),
          fetch(`/api/system/nodes/providers/routing-metadata?node_id=${encodeURIComponent(nodeId)}`, {
            credentials: "include",
            cache: "no-store",
          }),
        ]);

        const nodeBody = await nodeRes.json().catch(() => ({}));
        if (!nodeRes.ok) {
          const detail =
            typeof nodeBody?.detail === "string" ? nodeBody.detail : nodeBody?.detail?.error || `HTTP ${nodeRes.status}`;
          throw new Error(detail);
        }

        const routingBody = await routingRes.json().catch(() => ({}));
        const routingMatch = Array.isArray((routingBody as { nodes?: unknown[] }).nodes)
          ? ((routingBody as { nodes?: RoutingNodeGroup[] }).nodes || []).find((item) => item.node_id === nodeId) || null
          : null;

        if (!cancelled) {
          setNode(((nodeBody as { node?: NodeRecord }).node || null) as NodeRecord | null);
          setRouting(routingMatch);
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.message ?? String(e));
          setNode(null);
          setRouting(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    if (nodeId) {
      void load();
    } else {
      setLoading(false);
      setError("node_id_missing");
    }

    return () => {
      cancelled = true;
    };
  }, [nodeId]);

  const lifecycle = useMemo(() => (node ? lifecycleSteps(node) : []), [node]);
  const capabilityCategories = useMemo(() => node?.capabilities.taxonomy.categories || [], [node]);
  const routingProviders = useMemo(() => routing?.providers || [], [routing]);
  const nodeUiHref = useMemo(
    () => nodeUiFrameSrc(nodeId, node?.requested_ui_endpoint, node?.requested_hostname),
    [nodeId, node?.requested_hostname, node?.requested_ui_endpoint],
  );

  async function removeNode() {
    const target = String(nodeId || "").trim();
    if (!target || deleteBusy) return;
    setError(null);
    setDeleteBusy(true);
    try {
      const res = await fetch(`/api/system/nodes/registrations/${encodeURIComponent(target)}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) throw new Error(await readError(res));
      navigate("/addons", { replace: true });
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setDeleteBusy(false);
    }
  }

  return (
    <section className="node-page">
      <div className="node-hero">
        <div className="node-hero-copy">
          <Link to="/addons" className="node-back">
            Back to {branding.addonsName} &amp; {branding.nodesName}
          </Link>
          <div className="node-eyebrow">{branding.nodesName} Details</div>
          <h1 className="node-title">{node?.node_name || nodeId}</h1>
          <p className="node-subtitle">Canonical details for this trusted node from `/api/nodes/{nodeId}`.</p>
        </div>
        <div className="node-hero-actions">
          {nodeUiHref ? (
            <Link to={`/nodes/${encodeURIComponent(nodeId)}/UI`} className="node-btn">
              Open UI
            </Link>
          ) : null}
          <a href={`/api/nodes/${encodeURIComponent(nodeId)}`} target="_blank" rel="noreferrer" className="node-btn">
            Raw API
          </a>
          <a
            href={`/api/system/nodes/providers/routing-metadata?node_id=${encodeURIComponent(nodeId)}`}
            target="_blank"
            rel="noreferrer"
            className="node-btn"
          >
            Diagnostics
          </a>
          {isAdmin ? (
            <button className="node-btn node-btn-danger" type="button" onClick={() => void removeNode()} disabled={deleteBusy}>
              {deleteBusy ? "Removing..." : "Remove Node"}
            </button>
          ) : null}
        </div>
      </div>

      {loading ? (
        <div className="node-panel">Loading node details...</div>
      ) : error ? (
        <div className="node-error">{error}</div>
      ) : !node ? (
        <div className="node-error">Node not found.</div>
      ) : (
        <>
          <div className="node-summary-grid">
            <div className="node-summary-card">
              <div className="node-summary-label">Registry</div>
              <div className="node-summary-value">{sentenceCase(node.status.registry_state)}</div>
            </div>
            <div className="node-summary-card">
              <div className="node-summary-label">Trust</div>
              <div className="node-summary-value">{sentenceCase(node.status.trust_status)}</div>
            </div>
            <div className="node-summary-card">
              <div className="node-summary-label">Governance</div>
              <div className="node-summary-value">{sentenceCase(node.status.governance_sync_status)}</div>
            </div>
            <div className="node-summary-card">
              <div className="node-summary-label">Providers</div>
              <div className="node-summary-value">{routingProviders.length || node.provider_intelligence.length}</div>
            </div>
          </div>

          <div className="node-layout">
            <article className="node-panel">
              <div className="node-section-head">
                <h2>Overview</h2>
              </div>
              <div className="node-detail-grid">
                <div className="node-detail-card">
                  <div className="node-detail-label">Node ID</div>
                  <div className="node-detail-value node-code">{node.node_id}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Node Type</div>
                  <div className="node-detail-value">{sentenceCase(node.node_type)}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Requested Type</div>
                  <div className="node-detail-value">{sentenceCase(node.requested_node_type, "-")}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Version</div>
                  <div className="node-detail-value">{node.node_software_version || "-"}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Approved By</div>
                  <div className="node-detail-value">{node.approved_by_user_id || "-"}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Approved At</div>
                  <div className="node-detail-value">{formatTimestamp(node.approved_at)}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Hostname</div>
                  <div className="node-detail-value">{node.requested_hostname || "-"}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">UI Endpoint</div>
                  <div className="node-detail-value">{node.requested_ui_endpoint || "-"}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Requested API Base</div>
                  <div className="node-detail-value">{node.requested_api_base_url || "-"}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Resolved API Base</div>
                  <div className="node-detail-value">{node.api_base_url || "-"}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Onboarding Session</div>
                  <div className="node-detail-value node-code">{node.source_onboarding_session_id || "-"}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Created</div>
                  <div className="node-detail-value">{formatTimestamp(node.created_at)}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Updated</div>
                  <div className="node-detail-value">{formatTimestamp(node.updated_at)}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Governance Version</div>
                  <div className="node-detail-value">{node.status.active_governance_version || "-"}</div>
                </div>
              </div>
            </article>

            <article className="node-panel">
              <div className="node-section-head">
                <h2>Lifecycle</h2>
              </div>
              <div className="node-lifecycle">
                {lifecycle.map((step) => (
                  <div key={step.label} className={`node-step${step.complete ? " node-step-complete" : ""}`}>
                    <span className="node-step-icon">{step.complete ? "✓" : "○"}</span>
                    <span>{step.label}</span>
                  </div>
                ))}
              </div>
              <div className="node-detail-grid node-detail-grid-compact">
                <div className="node-detail-card">
                  <div className="node-detail-label">Capability Status</div>
                  <div className="node-detail-value">{sentenceCase(node.capabilities.capability_status)}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Activation Stage</div>
                  <div className="node-detail-value">{sentenceCase(node.capabilities.taxonomy.activation.stage)}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Operational Ready</div>
                  <div className="node-detail-value">{node.status.operational_ready ? "Yes" : "No"}</div>
                </div>
                <div className="node-detail-card">
                  <div className="node-detail-label">Capability Profile</div>
                  <div className="node-detail-value node-code">{node.capabilities.capability_profile_id || "-"}</div>
                </div>
              </div>
            </article>

            <article className="node-panel node-panel-full">
              <div className="node-section-head">
                <h2>Capabilities</h2>
              </div>
              {capabilityCategories.length === 0 ? (
                <div className="node-muted">No capability categories reported.</div>
              ) : (
                <div className="node-category-list">
                  {capabilityCategories.map((category) => (
                    <div key={category.category_id} className="node-category-card">
                      <div className="node-category-head">
                        <div className="node-category-title">{category.label}</div>
                        <div className="node-category-count">{category.item_count}</div>
                      </div>
                      {category.items.length === 0 ? (
                        <div className="node-muted">No items reported.</div>
                      ) : (
                        <div className="node-tag-list">
                          {category.items.map((item) => (
                            <span key={`${category.category_id}-${item}`} className="node-tag">
                              {item}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </article>

            <article className="node-panel node-panel-full">
              <div className="node-section-head">
                <h2>Providers</h2>
              </div>
              {routingProviders.length > 0 ? (
                <div className="node-provider-list">
                  {routingProviders.map((provider) => (
                    <div key={provider.provider} className="node-provider-card">
                      <div className="node-provider-head">
                        <div>
                          <div className="node-provider-title">{providerTitle(provider.provider)}</div>
                          <div className="node-muted">
                            {provider.models.length} models {routing?.node_available ? "available" : "reported"}
                          </div>
                        </div>
                      </div>
                      <div className="node-model-list">
                        {provider.models.map((model) => (
                          <div key={`${provider.provider}-${model.normalized_model_id}`} className="node-model-card">
                            <div className="node-model-title">{model.model_id}</div>
                            <div className="node-muted">Pricing: {formatMap(model.pricing)}</div>
                            <div className="node-muted">Latency: {formatMap(model.latency_metrics)}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : node.provider_intelligence.length > 0 ? (
                <div className="node-provider-list">
                  {node.provider_intelligence.map((provider) => (
                    <div key={String(provider.provider || "unknown")} className="node-provider-card">
                      <div className="node-provider-head">
                        <div>
                          <div className="node-provider-title">{providerTitle(provider.provider)}</div>
                          <div className="node-muted">{provider.available_models?.length || 0} models reported</div>
                        </div>
                      </div>
                      <div className="node-model-list">
                        {(provider.available_models || []).map((model) => (
                          <div key={`${provider.provider}-${model.normalized_model_id || model.model_id}`} className="node-model-card">
                            <div className="node-model-title">{model.model_id || model.normalized_model_id || "Unknown model"}</div>
                            <div className="node-muted">Pricing: {formatMap(model.pricing)}</div>
                            <div className="node-muted">Latency: {formatMap(model.latency_metrics)}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="node-muted">No provider intelligence reported for this node yet.</div>
              )}
            </article>
          </div>
        </>
      )}
    </section>
  );
}

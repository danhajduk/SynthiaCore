import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { usePlatformBranding } from "../branding";
import { nodeUiFrameSrc } from "./nodeFrameUrl";
import "./addon-frame.css";

type NodeUiPayload = {
  node?: {
    node_id?: string;
    node_name?: string;
    requested_hostname?: string | null;
    requested_ui_endpoint?: string | null;
  } | null;
};

export default function NodeFrame() {
  const branding = usePlatformBranding();
  const { nodeId = "" } = useParams();
  const [payload, setPayload] = useState<NodeUiPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}`, {
          credentials: "include",
          cache: "no-store",
        });
        const body = (await res.json().catch(() => ({}))) as NodeUiPayload & { detail?: string | { error?: string } };
        if (!res.ok) {
          const detail =
            typeof body.detail === "string" ? body.detail : body.detail?.error || `HTTP ${res.status}`;
          throw new Error(detail);
        }
        if (!cancelled) {
          setPayload(body);
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.message ?? String(e));
          setPayload(null);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
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

  const title = useMemo(() => {
    const fallbackTitle = nodeId || "unknown-node";
    return String(payload?.node?.node_name || fallbackTitle).trim() || fallbackTitle;
  }, [nodeId, payload]);
  const src = useMemo(
    () => nodeUiFrameSrc(payload?.node?.requested_ui_endpoint, payload?.node?.requested_hostname),
    [payload],
  );

  return (
    <section className="addon-frame-page">
      <header className="addon-frame-head">
        <h1 className="addon-frame-title">Node UI: {title}</h1>
        <div className="addon-frame-actions">
          <Link to={`/nodes/${encodeURIComponent(nodeId)}`} className="addon-frame-link">
            Back to {branding.nodesName}
          </Link>
          {src ? (
            <a href={src} target="_blank" rel="noreferrer" className="addon-frame-link">
              Open in new tab
            </a>
          ) : null}
        </div>
      </header>
      {loading ? (
        <div className="addon-frame-status">
          <strong>Loading node UI...</strong>
          <span>Resolving node metadata for {nodeId}.</span>
        </div>
      ) : error ? (
        <div className="addon-frame-status addon-frame-status-error">
          <strong>Node UI is not available.</strong>
          <span>{error}</span>
        </div>
      ) : !src ? (
        <div className="addon-frame-status addon-frame-status-error">
          <strong>Node UI is not available.</strong>
          <span>This node has no registered hostname yet, so Core cannot open its UI.</span>
        </div>
      ) : (
        <div className="addon-frame-embed-wrap">
          <iframe title={`node-ui-${nodeId}`} src={src} className="addon-frame-iframe" />
        </div>
      )}
    </section>
  );
}

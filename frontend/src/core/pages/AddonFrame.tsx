import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import "./addon-frame.css";
import { addonUiFrameSrc } from "./addonFrameUrl";
import { addonUiFallbackReason, resolveAddonUiEmbedState, type AddonUiStatusPayload } from "./addonFrameContract";
import { injectCoreCssIntoIframe } from "./addonFrameThemeInject";

type FramePhase = "checking" | "ready" | "fallback";

export default function AddonFrame() {
  const params = useParams<{ addonId: string }>();
  const addonId = (params.addonId || "").trim();
  const fallbackSrc = useMemo(() => addonUiFrameSrc(addonId), [addonId]);
  const [src, setSrc] = useState(fallbackSrc);
  const [phase, setPhase] = useState<FramePhase>("checking");
  const [reason, setReason] = useState("runtime_unavailable");
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const nonceRef = useRef(0);

  const probe = useCallback(async () => {
    if (!addonId) return;
    const nonce = Date.now();
    nonceRef.current = nonce;
    setPhase("checking");
    setIframeLoaded(false);
    setReason("runtime_unavailable");
    setSrc(fallbackSrc);

    const deadline = Date.now() + 20_000;
    while (Date.now() < deadline) {
      try {
        const res = await fetch(`/api/store/status/${encodeURIComponent(addonId)}`, { credentials: "include" });
        if (nonceRef.current !== nonce) return;
        if (res.ok) {
          const payload = (await res.json()) as AddonUiStatusPayload;
          const resolved = resolveAddonUiEmbedState(addonId, payload);
          setSrc(resolved.frameSrc);
          setReason(resolved.reason);
          if (resolved.reachable) {
            setPhase("ready");
            return;
          }
          const runtimeState = String(payload.runtime_state || "").trim().toLowerCase();
          if (runtimeState === "error") {
            setPhase("fallback");
            return;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 1500));
          continue;
        }
        setReason("status_error");
      } catch {
        setReason("status_error");
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }

    if (nonceRef.current !== nonce) return;
    setReason("timeout");
    setPhase("fallback");
  }, [addonId, fallbackSrc]);

  useEffect(() => {
    void probe();
    return () => {
      nonceRef.current = 0;
    };
  }, [probe]);

  if (!addonId) {
    return <div className="addon-frame-empty">Addon id is missing.</div>;
  }

  return (
    <section className="addon-frame-page">
      <header className="addon-frame-head">
        <h1 className="addon-frame-title">Addon UI: {addonId}</h1>
        <div className="addon-frame-actions">
          <a href={src} target="_blank" rel="noreferrer" className="addon-frame-link">
            Open in new tab
          </a>
          <Link to="/addons" className="addon-frame-link">
            Back to Addons
          </Link>
        </div>
      </header>
      {phase === "checking" && (
        <div className="addon-frame-status">
          <strong>Loading addon UI...</strong>
          <span>Waiting for addon runtime to report reachable UI endpoint.</span>
        </div>
      )}
      {phase === "fallback" && (
        <div className="addon-frame-status addon-frame-status-error">
          <strong>Addon UI is not ready.</strong>
          <span>{addonUiFallbackReason(reason)}</span>
          <button type="button" className="addon-frame-retry" onClick={() => void probe()}>
            Retry
          </button>
        </div>
      )}
      {phase === "ready" && (
        <div className="addon-frame-embed-wrap">
          {!iframeLoaded && (
            <div className="addon-frame-status">
              <strong>Opening addon UI...</strong>
              <span>Frame target: {src}</span>
            </div>
          )}
          <iframe
            ref={iframeRef}
            title={`addon-ui-${addonId}`}
            src={src}
            className="addon-frame-iframe"
            onLoad={() => {
              if (iframeRef.current) {
                injectCoreCssIntoIframe(iframeRef.current);
              }
              setIframeLoaded(true);
            }}
            onError={() => {
              setReason("frame_load_failed");
              setPhase("fallback");
            }}
          />
        </div>
      )}
    </section>
  );
}

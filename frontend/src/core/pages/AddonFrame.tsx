import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import "./addon-frame.css";
import { addonUiFrameSrc } from "./addonFrameUrl";
import { addonUiFallbackReason, resolveAddonUiEmbedState, type AddonUiStatusPayload } from "./addonFrameContract";
import { injectCoreCssIntoIframe } from "./addonFrameThemeInject";
import { resolveMqttSetupSection } from "./mqttSetupGate";

type FramePhase = "checking" | "ready" | "fallback";

export default function AddonFrame() {
  const params = useParams<{ addonId: string; section?: string }>();
  const navigate = useNavigate();
  const addonId = (params.addonId || "").trim();
  const requestedSection = String(params.section || "").trim();
  const fallbackSrc = useMemo(() => {
    const base = addonUiFrameSrc(addonId);
    if (!base) return "";
    if (!requestedSection) return base;
    return `${base}/${encodeURIComponent(requestedSection)}`;
  }, [addonId, requestedSection]);
  const [src, setSrc] = useState(fallbackSrc);
  const [phase, setPhase] = useState<FramePhase>("checking");
  const [reason, setReason] = useState("runtime_unavailable");
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const [themeInjectReason, setThemeInjectReason] = useState<string>("pending");
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const nonceRef = useRef(0);

  const probe = useCallback(async () => {
    if (!addonId) return;
    const nonce = Date.now();
    nonceRef.current = nonce;
    setPhase("checking");
    setIframeLoaded(false);
    setThemeInjectReason("pending");
    setReason("runtime_unavailable");
    setSrc(fallbackSrc);

    const deadline = Date.now() + 20_000;
    while (Date.now() < deadline) {
      try {
        const res = await fetch(`/api/store/status/${encodeURIComponent(addonId)}`, { credentials: "include" });
        if (nonceRef.current !== nonce) return;
        if (res.ok) {
          const payload = (await res.json()) as AddonUiStatusPayload;
          if (addonId === "mqtt") {
            try {
              const setupRes = await fetch("/api/system/mqtt/setup-summary", { credentials: "include", cache: "no-store" });
              if (setupRes.ok) {
                const setupPayload = await setupRes.json();
                const guard = resolveMqttSetupSection(requestedSection, setupPayload);
                if (guard.redirected) {
                  navigate(`/addons/mqtt/${guard.section}`, { replace: true });
                  return;
                }
              }
            } catch {
              // Ignore setup-summary errors and keep existing fallback behavior.
            }
          }
          const resolved = resolveAddonUiEmbedState(addonId, payload);
          let nextSrc = resolved.frameSrc;
          if (addonId === "mqtt" && requestedSection && nextSrc.includes(`/ui/addons/${encodeURIComponent(addonId)}`)) {
            const clean = nextSrc.replace(/\/+$/, "");
            nextSrc = `${clean}/${encodeURIComponent(requestedSection)}`;
          }
          setSrc(nextSrc);
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
  }, [addonId, fallbackSrc, navigate, requestedSection]);

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
          {iframeLoaded && themeInjectReason !== "ok" && (
            <div className="addon-frame-status addon-frame-status-error">
              <strong>Core theme CSS was not injected.</strong>
              <span>
                {themeInjectReason === "cross_origin"
                  ? "Frame is cross-origin (direct host:port), so browser security blocks parent CSS injection."
                  : "Theme injection failed for this frame document."}
              </span>
            </div>
          )}
          <iframe
            ref={iframeRef}
            title={`addon-ui-${addonId}`}
            src={src}
            className="addon-frame-iframe"
            onLoad={() => {
              let injected = false;
              let injectReason = "error";
              if (iframeRef.current) {
                const result = injectCoreCssIntoIframe(iframeRef.current);
                injected = result.injected;
                injectReason = result.reason;
                iframeRef.current.setAttribute("data-core-theme-injected", injected ? "true" : "false");
                iframeRef.current.setAttribute("data-core-theme-inject-reason", injectReason);
              }
              setThemeInjectReason(injectReason);
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

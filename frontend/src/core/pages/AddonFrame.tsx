import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import "./addon-frame.css";
import { addonUiFrameSrc } from "./addonFrameUrl";

export default function AddonFrame() {
  const params = useParams<{ addonId: string }>();
  const addonId = (params.addonId || "").trim();
  const src = useMemo(() => addonUiFrameSrc(addonId), [addonId]);

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
      <iframe title={`addon-ui-${addonId}`} src={src} className="addon-frame-iframe" />
    </section>
  );
}

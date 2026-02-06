import { useState } from "react";
import SystemStatsWidget from "../../components/SystemStatsWidget";
import "./settings.css";

export default function SettingsMetrics() {
  const [showStats, setShowStats] = useState(true);

  return (
    <div>
      <h1 className="settings-title">Settings / Metrics</h1>
      <p className="settings-muted">
        Live system and API health metrics.
      </p>

      <div className="settings-row">
        <div />
        <div className="settings-row-actions">
          <button className="settings-btn" onClick={() => setShowStats(v => !v)}>
            {showStats ? "Hide statistics" : "Show statistics"}
          </button>
        </div>
      </div>

      {showStats && <SystemStatsWidget />}
    </div>
  );
}

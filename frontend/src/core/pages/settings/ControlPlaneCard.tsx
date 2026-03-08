import { useState } from "react";
import "./admin-reload-card.css";

type MqttStatus = {
  connected: boolean;
  mode?: string | null;
  host?: string | null;
  port?: number | null;
  tls_enabled?: boolean | null;
  last_error?: string | null;
  message_count?: number;
  last_message_at?: string | null;
};

export default function ControlPlaneCard() {
  const [mqtt, setMqtt] = useState<MqttStatus | null>(null);
  const [capability, setCapability] = useState("jobs.enqueue");
  const [resolveOut, setResolveOut] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadMqtt() {
    setErr(null);
    try {
      const res = await fetch("/api/system/mqtt/status");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = (await res.json()) as MqttStatus;
      setMqtt(payload);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
      setMqtt(null);
    }
  }

  async function resolveService() {
    setErr(null);
    setBusy(true);
    try {
      const res = await fetch(`/api/services/resolve?capability=${encodeURIComponent(capability)}`);
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status} ${txt}`);
      }
      const payload = await res.json();
      setResolveOut(JSON.stringify(payload, null, 2));
    } catch (e: any) {
      setErr(e?.message ?? String(e));
      setResolveOut("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="admin-card">
      <div className="admin-header">
        <div>
          <div className="admin-title">Diagnostics / Service Resolver</div>
          <div className="admin-subtitle">Inspect MQTT status payloads and resolve capability routing for diagnostics.</div>
        </div>
      </div>

      <div className="admin-form">
        <div className="admin-log-label">Diagnostics Controls</div>
        <div className="admin-actions">
          <button className="admin-btn" onClick={loadMqtt}>Refresh MQTT Status</button>
        </div>
        {mqtt && (
          <pre className="admin-log">{JSON.stringify(mqtt, null, 2)}</pre>
        )}

        <label className="admin-label">
          <div className="admin-label-text">Resolve Capability</div>
          <input
            value={capability}
            onChange={(e) => setCapability(e.target.value)}
            className="admin-input admin-input-mono"
          />
        </label>
        <div className="admin-actions">
          <button className="admin-btn admin-btn-primary" onClick={resolveService} disabled={!capability.trim() || busy}>
            {busy ? "Resolving..." : "Resolve Service"}
          </button>
        </div>

        {resolveOut && <pre className="admin-log">{resolveOut}</pre>}
        {err && <pre className="admin-error">{err}</pre>}
      </div>
    </section>
  );
}

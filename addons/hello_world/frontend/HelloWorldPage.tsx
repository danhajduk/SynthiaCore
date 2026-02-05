import { useMemo, useState } from "react";

type EnqueueResult = { ok: boolean; job_id?: string; state?: string; error?: string };

const defaultPayload = JSON.stringify({ seconds: 1.5 }, null, 2);

export default function HelloWorldPage() {
  const [status, setStatus] = useState<any>(null);
  const [enqueueResult, setEnqueueResult] = useState<EnqueueResult | null>(null);
  const [burstResult, setBurstResult] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  const [jobType, setJobType] = useState("helloworld.sleep");
  const [priority, setPriority] = useState("normal");
  const [requestedUnits, setRequestedUnits] = useState(5);
  const [payload, setPayload] = useState(defaultPayload);
  const [idempotencyKey, setIdempotencyKey] = useState("");

  const [burstN, setBurstN] = useState(10);
  const [burstSeconds, setBurstSeconds] = useState(1.0);
  const [burstUnits, setBurstUnits] = useState(5);

  const canSubmit = useMemo(() => requestedUnits >= 1, [requestedUnits]);

  async function fetchStatus() {
    setErr(null);
    try {
      const res = await fetch("/api/addons/hello_world/status");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatus(await res.json());
    } catch (e: any) {
      setErr(String(e));
    }
  }

  async function enqueueJob() {
    setErr(null);
    setEnqueueResult(null);
    try {
      const body = {
        job_type: jobType,
        priority,
        requested_units: requestedUnits,
        payload: payload ? JSON.parse(payload) : {},
        idempotency_key: idempotencyKey || null,
      };
      const res = await fetch("/api/addons/hello_world/jobs/enqueue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setEnqueueResult(await res.json());
    } catch (e: any) {
      setErr(String(e));
    }
  }

  async function burstJobs() {
    setErr(null);
    setBurstResult(null);
    try {
      const params = new URLSearchParams({
        n: String(burstN),
        seconds: String(burstSeconds),
        units: String(burstUnits),
      });
      const res = await fetch(`/api/addons/hello_world/jobs/burst?${params.toString()}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setBurstResult(await res.json());
    } catch (e: any) {
      setErr(String(e));
    }
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div>
        <h1 style={{ marginTop: 0 }}>Hello World</h1>
        <div style={{ opacity: 0.8 }}>Addon UI with scheduler enqueue controls.</div>
      </div>

      <section
        style={{
          padding: 12,
          borderRadius: 14,
          border: "1px solid rgba(255,255,255,0.1)",
          background: "rgba(255,255,255,0.04)",
        }}
      >
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Backend Status</div>
        <button
          onClick={fetchStatus}
          style={{
            padding: "8px 12px",
            borderRadius: 10,
            border: "1px solid rgba(255,255,255,0.15)",
            background: "rgba(255,255,255,0.06)",
            color: "white",
            cursor: "pointer",
          }}
        >
          Fetch status
        </button>
        {status && (
          <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>
            {JSON.stringify(status, null, 2)}
          </pre>
        )}
      </section>

      <section
        style={{
          padding: 12,
          borderRadius: 14,
          border: "1px solid rgba(255,255,255,0.1)",
          background: "rgba(255,255,255,0.04)",
        }}
      >
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Enqueue One Job</div>
        <div style={{ display: "grid", gap: 8, maxWidth: 520 }}>
          <label>
            <div style={{ fontSize: 12, opacity: 0.8 }}>Job type</div>
            <input
              value={jobType}
              onChange={(e) => setJobType(e.target.value)}
              style={{ width: "100%", padding: 8, borderRadius: 8 }}
            />
          </label>
          <label>
            <div style={{ fontSize: 12, opacity: 0.8 }}>Priority</div>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              style={{ width: "100%", padding: 8, borderRadius: 8 }}
            >
              <option value="high">high</option>
              <option value="normal">normal</option>
              <option value="low">low</option>
              <option value="background">background</option>
            </select>
          </label>
          <label>
            <div style={{ fontSize: 12, opacity: 0.8 }}>Requested units</div>
            <input
              type="number"
              min={1}
              value={requestedUnits}
              onChange={(e) => setRequestedUnits(Number(e.target.value))}
              style={{ width: "100%", padding: 8, borderRadius: 8 }}
            />
          </label>
          <label>
            <div style={{ fontSize: 12, opacity: 0.8 }}>Payload (JSON)</div>
            <textarea
              rows={5}
              value={payload}
              onChange={(e) => setPayload(e.target.value)}
              style={{ width: "100%", padding: 8, borderRadius: 8 }}
            />
          </label>
          <label>
            <div style={{ fontSize: 12, opacity: 0.8 }}>Idempotency key (optional)</div>
            <input
              value={idempotencyKey}
              onChange={(e) => setIdempotencyKey(e.target.value)}
              style={{ width: "100%", padding: 8, borderRadius: 8 }}
            />
          </label>
          <button
            onClick={enqueueJob}
            disabled={!canSubmit}
            style={{
              padding: "8px 12px",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.06)",
              color: "white",
              cursor: canSubmit ? "pointer" : "not-allowed",
              opacity: canSubmit ? 1 : 0.6,
            }}
          >
            Enqueue job
          </button>
          {enqueueResult && (
            <pre style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>
              {JSON.stringify(enqueueResult, null, 2)}
            </pre>
          )}
        </div>
      </section>

      <section
        style={{
          padding: 12,
          borderRadius: 14,
          border: "1px solid rgba(255,255,255,0.1)",
          background: "rgba(255,255,255,0.04)",
        }}
      >
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Burst Enqueue</div>
        <div style={{ display: "grid", gap: 8, maxWidth: 520 }}>
          <label>
            <div style={{ fontSize: 12, opacity: 0.8 }}>Jobs</div>
            <input
              type="number"
              min={1}
              max={500}
              value={burstN}
              onChange={(e) => setBurstN(Number(e.target.value))}
              style={{ width: "100%", padding: 8, borderRadius: 8 }}
            />
          </label>
          <label>
            <div style={{ fontSize: 12, opacity: 0.8 }}>Sleep seconds</div>
            <input
              type="number"
              min={0.1}
              step={0.1}
              value={burstSeconds}
              onChange={(e) => setBurstSeconds(Number(e.target.value))}
              style={{ width: "100%", padding: 8, borderRadius: 8 }}
            />
          </label>
          <label>
            <div style={{ fontSize: 12, opacity: 0.8 }}>Units per job</div>
            <input
              type="number"
              min={1}
              value={burstUnits}
              onChange={(e) => setBurstUnits(Number(e.target.value))}
              style={{ width: "100%", padding: 8, borderRadius: 8 }}
            />
          </label>
          <button
            onClick={burstJobs}
            style={{
              padding: "8px 12px",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.06)",
              color: "white",
              cursor: "pointer",
            }}
          >
            Enqueue burst
          </button>
          {burstResult && (
            <pre style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>
              {JSON.stringify(burstResult, null, 2)}
            </pre>
          )}
        </div>
      </section>

      {err && (
        <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>
          {err}
        </pre>
      )}
    </div>
  );
}

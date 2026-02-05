import { useMemo, useState } from "react";
import "./style.css";

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
    <div className="hw-page">
      <div>
        <h1 className="hw-title">Hello World</h1>
        <div className="hw-muted">Addon UI with scheduler enqueue controls.</div>
      </div>

      <section className="hw-card">
        <div className="hw-card-title">Backend Status</div>
        <button
          onClick={fetchStatus}
          className="hw-btn"
        >
          Fetch status
        </button>
        {status && (
          <pre className="hw-pre">
            {JSON.stringify(status, null, 2)}
          </pre>
        )}
      </section>

      <section className="hw-card">
        <div className="hw-card-title">Enqueue One Job</div>
        <div className="hw-form">
          <label className="hw-label">
            <div className="hw-label-text">Job type</div>
            <input
              value={jobType}
              onChange={(e) => setJobType(e.target.value)}
              className="hw-input"
            />
          </label>
          <label className="hw-label">
            <div className="hw-label-text">Priority</div>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              className="hw-select"
            >
              <option value="high">high</option>
              <option value="normal">normal</option>
              <option value="low">low</option>
              <option value="background">background</option>
            </select>
          </label>
          <label className="hw-label">
            <div className="hw-label-text">Requested units</div>
            <input
              type="number"
              min={1}
              value={requestedUnits}
              onChange={(e) => setRequestedUnits(Number(e.target.value))}
              className="hw-input"
            />
          </label>
          <label className="hw-label">
            <div className="hw-label-text">Payload (JSON)</div>
            <textarea
              rows={5}
              value={payload}
              onChange={(e) => setPayload(e.target.value)}
              className="hw-textarea"
            />
          </label>
          <label className="hw-label">
            <div className="hw-label-text">Idempotency key (optional)</div>
            <input
              value={idempotencyKey}
              onChange={(e) => setIdempotencyKey(e.target.value)}
              className="hw-input"
            />
          </label>
          <button
            onClick={enqueueJob}
            disabled={!canSubmit}
            className="hw-btn"
          >
            Enqueue job
          </button>
          {enqueueResult && (
            <pre className="hw-pre-tight">
              {JSON.stringify(enqueueResult, null, 2)}
            </pre>
          )}
        </div>
      </section>

      <section className="hw-card">
        <div className="hw-card-title">Burst Enqueue</div>
        <div className="hw-form">
          <label className="hw-label">
            <div className="hw-label-text">Jobs</div>
            <input
              type="number"
              min={1}
              max={500}
              value={burstN}
              onChange={(e) => setBurstN(Number(e.target.value))}
              className="hw-input"
            />
          </label>
          <label className="hw-label">
            <div className="hw-label-text">Sleep seconds</div>
            <input
              type="number"
              min={0.1}
              step={0.1}
              value={burstSeconds}
              onChange={(e) => setBurstSeconds(Number(e.target.value))}
              className="hw-input"
            />
          </label>
          <label className="hw-label">
            <div className="hw-label-text">Units per job</div>
            <input
              type="number"
              min={1}
              value={burstUnits}
              onChange={(e) => setBurstUnits(Number(e.target.value))}
              className="hw-input"
            />
          </label>
          <button
            onClick={burstJobs}
            className="hw-btn"
          >
            Enqueue burst
          </button>
          {burstResult && (
            <pre className="hw-pre-tight">
              {JSON.stringify(burstResult, null, 2)}
            </pre>
          )}
        </div>
      </section>

      {err && (
        <pre className="hw-error">
          {err}
        </pre>
      )}
    </div>
  );
}

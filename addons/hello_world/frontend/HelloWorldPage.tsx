import { useEffect, useMemo, useRef, useState } from "react";
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

  const [acquireWorkerId, setAcquireWorkerId] = useState("hello-world-ui");
  const [acquireMaxUnits, setAcquireMaxUnits] = useState("");
  const [acquireIntervalMs, setAcquireIntervalMs] = useState(1500);
  const [autoCompleteEnabled, setAutoCompleteEnabled] = useState(true);
  const [autoCompleteDelayMs, setAutoCompleteDelayMs] = useState(2000);
  const [autoCompleteStatus, setAutoCompleteStatus] = useState<"completed" | "failed">(
    "completed"
  );
  const [acquireResult, setAcquireResult] = useState<any>(null);
  const [acquiring, setAcquiring] = useState(false);
  const acquireTimerRef = useRef<number | null>(null);
  const completeTimersRef = useRef<number[]>([]);

  const canSubmit = useMemo(() => requestedUnits >= 1, [requestedUnits]);

  useEffect(() => {
    return () => {
      if (acquireTimerRef.current !== null) {
        window.clearInterval(acquireTimerRef.current);
        acquireTimerRef.current = null;
      }
      if (completeTimersRef.current.length > 0) {
        completeTimersRef.current.forEach((timerId) => window.clearTimeout(timerId));
        completeTimersRef.current = [];
      }
    };
  }, []);

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

  async function requestLease() {
    setErr(null);
    setAcquireResult(null);
    try {
      const body: { worker_id: string; max_units?: number } = {
        worker_id: acquireWorkerId || "hello-world-ui",
      };
      const parsedUnits = Number(acquireMaxUnits);
      if (!Number.isNaN(parsedUnits) && parsedUnits > 0) {
        body.max_units = parsedUnits;
      }
      const res = await fetch("/api/system/scheduler/leases/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setAcquireResult(data);

      if (autoCompleteEnabled && data?.denied === false && data?.lease?.lease_id) {
        const leaseId = data.lease.lease_id as string;
        const workerId = body.worker_id;
        const delayMs = Math.max(0, Number(autoCompleteDelayMs) || 0);
        const timerId = window.setTimeout(() => {
          completeLease(leaseId, workerId, autoCompleteStatus);
        }, delayMs);
        completeTimersRef.current.push(timerId);
      }
    } catch (e: any) {
      setErr(String(e));
    }
  }

  async function completeLease(leaseId: string, workerId: string, status: "completed" | "failed") {
    try {
      const res = await fetch(`/api/system/scheduler/leases/${leaseId}/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ worker_id: workerId, status }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (e: any) {
      setErr(String(e));
    }
  }

  function startAcquiring() {
    if (acquiring) return;
    setAcquiring(true);
    requestLease();
    if (acquireTimerRef.current !== null) {
      window.clearInterval(acquireTimerRef.current);
    }
    acquireTimerRef.current = window.setInterval(() => {
      requestLease();
    }, Math.max(500, Number(acquireIntervalMs) || 1500));
  }

  function stopAcquiring() {
    setAcquiring(false);
    if (acquireTimerRef.current !== null) {
      window.clearInterval(acquireTimerRef.current);
      acquireTimerRef.current = null;
    }
    if (completeTimersRef.current.length > 0) {
      completeTimersRef.current.forEach((timerId) => window.clearTimeout(timerId));
      completeTimersRef.current = [];
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

      <section className="hw-card">
        <div className="hw-card-title">Acquire Jobs (Scheduler)</div>
        <div className="hw-form">
          <label className="hw-label">
            <div className="hw-label-text">Worker id</div>
            <input
              value={acquireWorkerId}
              onChange={(e) => setAcquireWorkerId(e.target.value)}
              className="hw-input"
            />
          </label>
          <label className="hw-label">
            <div className="hw-label-text">Max units (optional)</div>
            <input
              type="number"
              min={1}
              value={acquireMaxUnits}
              onChange={(e) => setAcquireMaxUnits(e.target.value)}
              className="hw-input"
            />
          </label>
          <label className="hw-label">
            <div className="hw-label-text">Acquire interval (ms)</div>
            <input
              type="number"
              min={500}
              step={100}
              value={acquireIntervalMs}
              onChange={(e) => setAcquireIntervalMs(Number(e.target.value))}
              className="hw-input"
            />
          </label>
          <label className="hw-label">
            <div className="hw-label-text">Auto-complete after (ms)</div>
            <input
              type="number"
              min={0}
              step={100}
              value={autoCompleteDelayMs}
              onChange={(e) => setAutoCompleteDelayMs(Number(e.target.value))}
              className="hw-input"
            />
          </label>
          <label className="hw-label">
            <div className="hw-label-text">Auto-complete status</div>
            <select
              value={autoCompleteStatus}
              onChange={(e) => setAutoCompleteStatus(e.target.value as "completed" | "failed")}
              className="hw-select"
            >
              <option value="completed">completed</option>
              <option value="failed">failed</option>
            </select>
          </label>
          <label className="hw-checkbox">
            <input
              type="checkbox"
              checked={autoCompleteEnabled}
              onChange={(e) => setAutoCompleteEnabled(e.target.checked)}
            />
            <span>Auto-complete leases after delay</span>
          </label>
          <div className="hw-actions">
            <button
              onClick={startAcquiring}
              disabled={acquiring}
              className="hw-btn"
            >
              Start acquiring
            </button>
            <button
              onClick={stopAcquiring}
              disabled={!acquiring}
              className="hw-btn"
            >
              Stop
            </button>
            <button
              onClick={requestLease}
              className="hw-btn"
            >
              Acquire once
            </button>
          </div>
          {acquireResult && (
            <pre className="hw-pre-tight">
              {JSON.stringify(acquireResult, null, 2)}
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

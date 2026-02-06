import { useEffect, useState } from "react";
import SystemStatsWidget from "../../components/SystemStatsWidget";
import "./settings.css";

type JobState = "queued" | "leased" | "running" | "completed" | "failed" | "expired";

type SchedulerJob = {
  job_id: string;
  requested_units: number;
  state: JobState;
};

type JobsResponse = {
  jobs: {
    job: SchedulerJob;
  }[];
};

export default function SettingsMetrics() {
  const [showStats, setShowStats] = useState(true);
  const [jobsSummary, setJobsSummary] = useState<{ queued: number; leased: number; leasedUnits: number }>({
    queued: 0,
    leased: 0,
    leasedUnits: 0,
  });
  const [summaryErr, setSummaryErr] = useState<string | null>(null);

  async function loadJobsSummary() {
    try {
      setSummaryErr(null);
      const res = await fetch("/api/system/scheduler/jobs?limit=500");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = (await res.json()) as JobsResponse;
      let queued = 0;
      let leased = 0;
      let leasedUnits = 0;
      for (const entry of payload.jobs) {
        if (entry.job.state === "queued") {
          queued += 1;
        }
        if (entry.job.state === "leased") {
          leased += 1;
          leasedUnits += entry.job.requested_units || 0;
        }
      }
      setJobsSummary({ queued, leased, leasedUnits });
    } catch (e: any) {
      setSummaryErr(e?.message ?? String(e));
    }
  }

  useEffect(() => {
    loadJobsSummary();
    const t = setInterval(loadJobsSummary, 5000);
    return () => clearInterval(t);
  }, []);

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

      <div className="settings-card">
        <div className="settings-card-title">Jobs Summary</div>
        {summaryErr && <div className="settings-error">Failed to load jobs summary: {summaryErr}</div>}
        {!summaryErr && (
          <div className="settings-stats-kv">
            <span>Queued</span>
            <strong>{jobsSummary.queued} jobs</strong>
          </div>
        )}
        {!summaryErr && (
          <div className="settings-stats-kv">
            <span>Leased</span>
            <strong>{jobsSummary.leased} jobs, {jobsSummary.leasedUnits} units</strong>
          </div>
        )}
      </div>

      {showStats && <SystemStatsWidget />}
    </div>
  );
}

import SystemStatsWidget from "../../components/SystemStatsWidget";
import AdminReloadCard from "./settings/AdminReloadCard";
import "./settings.css";
import { useEffect, useMemo, useState } from "react";

type JobState = "queued" | "leased" | "running" | "completed" | "failed" | "expired";
type JobPriority = "high" | "normal" | "low" | "background";

type SchedulerJob = {
  job_id: string;
  type: string;
  priority: JobPriority;
  requested_units: number;
  unique?: boolean;
  state: JobState;
  payload: Record<string, unknown>;
  idempotency_key?: string | null;
  tags: string[];
  max_runtime_s?: number | null;
  lease_id?: string | null;
  created_at: string;
  updated_at: string;
};

type SchedulerLease = {
  lease_id: string;
  job_id: string;
  worker_id: string;
  capacity_units: number;
  issued_at: string;
  expires_at: string;
  last_heartbeat: string;
};

type JobsResponse = {
  now: string;
  store_id: string;
  jobs_len: number;
  leases_len: number;
  queue_depths: Record<string, number>;
  snapshot: {
    busy_rating: number;
    total_capacity_units: number;
    usable_capacity_units: number;
    leased_capacity_units: number;
    available_capacity_units: number;
    queue_depths: Record<string, number>;
    active_leases: number;
  };
  jobs: {
    job: SchedulerJob;
    lease: SchedulerLease | null;
    in_queue: boolean;
    age_s: number;
    since_update_s: number;
  }[];
};

export default function Settings() {
  const showDevTools = import.meta.env.DEV;
  const [jobsData, setJobsData] = useState<JobsResponse | null>(null);
  const [jobsErr, setJobsErr] = useState<string | null>(null);
  const [showStats, setShowStats] = useState(true);
  const [showJobs, setShowJobs] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [stateFilter, setStateFilter] = useState<JobState | "all">("all");
  const [limit, setLimit] = useState(100);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  async function loadJobs() {
    try {
      setJobsErr(null);
      const params = new URLSearchParams();
      params.set("limit", String(limit));
      if (stateFilter !== "all") params.set("state", stateFilter);
      const res = await fetch(`/api/system/scheduler/jobs?${params.toString()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = (await res.json()) as JobsResponse;
      setJobsData(payload);
      if (selectedJobId && !payload.jobs.some(j => j.job.job_id === selectedJobId)) {
        setSelectedJobId(null);
      }
    } catch (e: any) {
      setJobsErr(e?.message ?? String(e));
    }
  }

  useEffect(() => {
    loadJobs();
    if (!autoRefresh) return;
    const t = setInterval(loadJobs, 4000);
    return () => clearInterval(t);
  }, [autoRefresh, stateFilter, limit]);

  const selectedJob = useMemo(() => {
    if (!selectedJobId || !jobsData) return null;
    return jobsData.jobs.find(j => j.job.job_id === selectedJobId) ?? null;
  }, [jobsData, selectedJobId]);

  return (
    <div>
      <h1 className="settings-title">Settings</h1>
      <p>Placeholder system settings page.</p>

      <hr className="settings-hr" />

      <h2>System</h2>
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

      <hr className="settings-hr" />

      <div className="settings-row">
        <div>
          <h2>Scheduler Jobs</h2>
          <p className="settings-muted">Live view of scheduler jobs, leases, and queue state.</p>
        </div>
        <div className="settings-row-actions">
          <button className="settings-btn" onClick={() => setShowJobs(v => !v)}>
            {showJobs ? "Hide jobs" : "Show jobs"}
          </button>
          <button className="settings-btn" onClick={loadJobs}>Refresh</button>
        </div>
      </div>

      {showJobs && (
        <div className="settings-jobs-panel">
          <div className="settings-row settings-jobs-controls">
            <div className="settings-toggle">
              <input
                id="jobs-auto"
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              <label htmlFor="jobs-auto">Auto refresh</label>
            </div>

            <div className="settings-select">
              <label htmlFor="jobs-state">State</label>
              <select
                id="jobs-state"
                value={stateFilter}
                onChange={(e) => setStateFilter(e.target.value as JobState | "all")}
              >
                <option value="all">All</option>
                <option value="queued">Queued</option>
                <option value="leased">Leased</option>
                <option value="running">Running</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
                <option value="expired">Expired</option>
              </select>
            </div>

            <div className="settings-select">
              <label htmlFor="jobs-limit">Limit</label>
              <select
                id="jobs-limit"
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
              >
                <option value={50}>50</option>
                <option value={100}>100</option>
                <option value={200}>200</option>
                <option value={500}>500</option>
              </select>
            </div>
          </div>

          {jobsErr && (
            <div className="settings-error">Failed to load jobs: {jobsErr}</div>
          )}

          {!jobsErr && !jobsData && (
            <div className="settings-loading">Loading jobs…</div>
          )}

          {jobsData && (
            <>
              <div className="settings-jobs-meta">
                <div>
                  <div className="settings-mono">Store {jobsData.store_id}</div>
                  <div className="settings-muted">
                    Jobs {jobsData.jobs_len} • Leases {jobsData.leases_len} • Updated {new Date(jobsData.now).toLocaleTimeString()}
                  </div>
                </div>
                <div className="settings-meta-badges">
                  <span className="settings-pill">Busy {jobsData.snapshot.busy_rating}/10</span>
                  <span className="settings-pill">Available {jobsData.snapshot.available_capacity_units} units</span>
                  <span className="settings-pill">Leased {jobsData.snapshot.leased_capacity_units} units</span>
                </div>
              </div>

              {(() => {
                const topJobs = jobsData.jobs.filter((entry) =>
                  entry.job.state === "queued" || entry.job.state === "leased"
                );
                const bottomJobs = jobsData.jobs.filter((entry) =>
                  entry.job.state === "completed" || entry.job.state === "failed"
                );
                return (
                  <>
                    <div className="settings-row">
                      <h3>Queue / Leased</h3>
                      <div className="settings-muted">{topJobs.length} jobs</div>
                    </div>
                    <div className="settings-jobs-grid">
                      {topJobs.map((entry) => (
                        <button
                          key={entry.job.job_id}
                          className={`settings-job-card ${selectedJobId === entry.job.job_id ? "is-selected" : ""}`}
                          onClick={() => setSelectedJobId(entry.job.job_id)}
                        >
                          <div className="settings-job-row">
                            <div className="settings-job-id">{entry.job.job_id}</div>
                            <span className={`settings-state settings-state-${entry.job.state}`}>{entry.job.state}</span>
                          </div>
                          <div className="settings-job-sub">{entry.job.type}</div>
                          <div className="settings-job-meta">
                            <span>prio {entry.job.priority}</span>
                            <span>units {entry.job.requested_units}</span>
                            <span>{entry.job.unique ? "unique" : "shared"}</span>
                            <span>{entry.in_queue ? "queued" : "not queued"}</span>
                          </div>
                          <div className="settings-job-meta">
                            <span>age {Math.round(entry.age_s)}s</span>
                            <span>updated {Math.round(entry.since_update_s)}s ago</span>
                          </div>
                        </button>
                      ))}
                    </div>

                    <div className="settings-row">
                      <h3>Completed / Failed</h3>
                      <div className="settings-muted">{bottomJobs.length} jobs</div>
                    </div>
                    <div className="settings-jobs-grid">
                      {bottomJobs.map((entry) => (
                        <button
                          key={entry.job.job_id}
                          className={`settings-job-card ${selectedJobId === entry.job.job_id ? "is-selected" : ""}`}
                          onClick={() => setSelectedJobId(entry.job.job_id)}
                        >
                          <div className="settings-job-row">
                            <div className="settings-job-id">{entry.job.job_id}</div>
                            <span className={`settings-state settings-state-${entry.job.state}`}>{entry.job.state}</span>
                          </div>
                          <div className="settings-job-sub">{entry.job.type}</div>
                          <div className="settings-job-meta">
                            <span>prio {entry.job.priority}</span>
                            <span>units {entry.job.requested_units}</span>
                            <span>{entry.job.unique ? "unique" : "shared"}</span>
                            <span>{entry.in_queue ? "queued" : "not queued"}</span>
                          </div>
                          <div className="settings-job-meta">
                            <span>age {Math.round(entry.age_s)}s</span>
                            <span>updated {Math.round(entry.since_update_s)}s ago</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  </>
                );
              })()}

              <div className="settings-job-detail">
                <div className="settings-job-detail-header">
                  <h3>Job Detail</h3>
                  {selectedJob ? (
                    <span className="settings-mono">{selectedJob.job.job_id}</span>
                  ) : (
                    <span className="settings-muted">Select a job to inspect details.</span>
                  )}
                </div>

                {selectedJob && (
                  <div className="settings-job-detail-grid">
                    <div className="settings-detail-card">
                      <div className="settings-detail-title">Job</div>
                      <pre className="settings-pre">{JSON.stringify(selectedJob.job, null, 2)}</pre>
                    </div>
                    <div className="settings-detail-card">
                      <div className="settings-detail-title">Lease</div>
                      <pre className="settings-pre">
                        {selectedJob.lease ? JSON.stringify(selectedJob.lease, null, 2) : "No active lease"}
                      </pre>
                    </div>
                    <div className="settings-detail-card">
                      <div className="settings-detail-title">Debug</div>
                      <pre className="settings-pre">
                        {JSON.stringify(
                          {
                            in_queue: selectedJob.in_queue,
                            age_s: selectedJob.age_s,
                            since_update_s: selectedJob.since_update_s,
                            queue_depths: jobsData.queue_depths,
                            snapshot: jobsData.snapshot,
                          },
                          null,
                          2
                        )}
                      </pre>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {showDevTools && (
        <>
          <hr className="settings-hr-wide" />
          <h2>Developer Tools</h2>
          <AdminReloadCard />
        </>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import "./header.css";

type RepoStatus = {
  ok: boolean;
  update_available?: boolean;
  status?: string;
  error?: string;
};

export default function Header() {
  const [repoStatus, setRepoStatus] = useState<RepoStatus | null>(null);

  async function loadRepoStatus() {
    try {
      const res = await fetch("/api/system/repo/status");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = (await res.json()) as RepoStatus;
      setRepoStatus(payload);
    } catch {
      setRepoStatus({ ok: false, error: "unavailable" });
    }
  }

  useEffect(() => {
    loadRepoStatus();
    const t = setInterval(loadRepoStatus, 60000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className="header">
      <div>
        <div className="header-title">Synthia</div>
        <div className="header-subtitle">Core shell + Addons</div>
      </div>
      <div className="header-right">
        {repoStatus?.ok && repoStatus.update_available && (
          <span className="header-badge header-badge-warn">Update available</span>
        )}
        {repoStatus?.ok && !repoStatus.update_available && (
          <span className="header-badge">Up to date</span>
        )}
        {!repoStatus?.ok && (
          <span className="header-badge header-badge-muted">Repo status unavailable</span>
        )}
      </div>
    </header>
  );
}

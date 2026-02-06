# backend/app/system/scheduler/history.py
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import Job, Lease


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime | None) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def _from_iso(val: str | None) -> Optional[datetime]:
    if not val:
        return None
    return datetime.fromisoformat(val)


def _addon_from_tags(tags: Iterable[str]) -> Optional[str]:
    for tag in tags:
        if tag.startswith("addon:"):
            return tag.split(":", 1)[1] or None
    return None


@dataclass
class HistoryStats:
    range_start: datetime
    range_end: datetime
    total: int
    totals_by_state: Dict[str, int]
    success_rate: Optional[float]
    avg_queue_wait_s: Optional[float]
    addons: List[Dict[str, Any]]


class SchedulerHistoryStore:
    """
    SQLite-backed job history store. Keeps non-queued jobs only.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()
        self._init_db()

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS job_history (
              job_id TEXT PRIMARY KEY,
              type TEXT,
              priority TEXT,
              requested_units INTEGER,
              unique_flag INTEGER,
              state TEXT,
              payload_json TEXT,
              tags_json TEXT,
              addon_id TEXT,
              idempotency_key TEXT,
              lease_id TEXT,
              worker_id TEXT,
              created_at TEXT,
              updated_at TEXT,
              leased_at TEXT,
              finished_at TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_job_history_updated ON job_history(updated_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_job_history_addon ON job_history(addon_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_job_history_state ON job_history(state)")
        self._conn.commit()

    async def record_lease(self, job: Job, lease: Lease) -> None:
        await self._run(self._record_lease_sync, job, lease)

    async def update_state(
        self,
        job: Job,
        lease: Lease | None,
        finished_at: datetime | None = None,
    ) -> None:
        await self._run(self._update_state_sync, job, lease, finished_at)

    async def record_expired(self, expired: Iterable[Tuple[Lease, Job | None]]) -> None:
        await self._run(self._record_expired_sync, list(expired))

    async def cleanup(self, days: int = 30) -> int:
        return await self._run(self._cleanup_sync, int(days))

    async def stats(self, days: int = 30) -> HistoryStats:
        return await self._run(self._stats_sync, int(days))

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    def _record_lease_sync(self, job: Job, lease: Lease) -> None:
        now = _to_iso(job.updated_at)
        addon_id = _addon_from_tags(job.tags)
        self._conn.execute(
            """
            INSERT INTO job_history (
              job_id, type, priority, requested_units, unique_flag, state,
              payload_json, tags_json, addon_id, idempotency_key,
              lease_id, worker_id, created_at, updated_at, leased_at, finished_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
              type=excluded.type,
              priority=excluded.priority,
              requested_units=excluded.requested_units,
              unique_flag=excluded.unique_flag,
              state=excluded.state,
              payload_json=excluded.payload_json,
              tags_json=excluded.tags_json,
              addon_id=excluded.addon_id,
              idempotency_key=excluded.idempotency_key,
              lease_id=excluded.lease_id,
              worker_id=excluded.worker_id,
              created_at=excluded.created_at,
              updated_at=excluded.updated_at,
              leased_at=COALESCE(job_history.leased_at, excluded.leased_at)
            """,
            (
                job.job_id,
                job.type,
                str(job.priority),
                int(job.requested_units),
                1 if job.unique else 0,
                str(job.state),
                json.dumps(job.payload or {}),
                json.dumps(job.tags or []),
                addon_id,
                job.idempotency_key,
                lease.lease_id,
                lease.worker_id,
                _to_iso(job.created_at),
                now,
                _to_iso(lease.issued_at),
                None,
            ),
        )
        self._conn.commit()

    def _update_state_sync(
        self,
        job: Job,
        lease: Lease | None,
        finished_at: datetime | None,
    ) -> None:
        addon_id = _addon_from_tags(job.tags)
        lease_id = lease.lease_id if lease else job.lease_id
        worker_id = lease.worker_id if lease else None
        leased_at = None
        if lease:
            leased_at = lease.issued_at
        elif job.state in ("leased", "running"):
            leased_at = job.updated_at

        self._conn.execute(
            """
            INSERT INTO job_history (
              job_id, type, priority, requested_units, unique_flag, state,
              payload_json, tags_json, addon_id, idempotency_key,
              lease_id, worker_id, created_at, updated_at, leased_at, finished_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
              type=excluded.type,
              priority=excluded.priority,
              requested_units=excluded.requested_units,
              unique_flag=excluded.unique_flag,
              state=excluded.state,
              payload_json=excluded.payload_json,
              tags_json=excluded.tags_json,
              addon_id=excluded.addon_id,
              idempotency_key=excluded.idempotency_key,
              lease_id=COALESCE(excluded.lease_id, job_history.lease_id),
              worker_id=COALESCE(excluded.worker_id, job_history.worker_id),
              created_at=excluded.created_at,
              updated_at=excluded.updated_at,
              leased_at=COALESCE(job_history.leased_at, excluded.leased_at),
              finished_at=COALESCE(excluded.finished_at, job_history.finished_at)
            """,
            (
                job.job_id,
                job.type,
                str(job.priority),
                int(job.requested_units),
                1 if job.unique else 0,
                str(job.state),
                json.dumps(job.payload or {}),
                json.dumps(job.tags or []),
                addon_id,
                job.idempotency_key,
                lease_id,
                worker_id,
                _to_iso(job.created_at),
                _to_iso(job.updated_at),
                _to_iso(leased_at),
                _to_iso(finished_at),
            ),
        )
        self._conn.commit()

    def _record_expired_sync(self, expired: List[Tuple[Lease, Job | None]]) -> None:
        now = _utcnow()
        for lease, job in expired:
            if not job:
                continue
            if job.state != "expired":
                continue
            self._update_state_sync(job, lease, finished_at=now)

    def _cleanup_sync(self, days: int) -> int:
        cutoff = _utcnow() - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()
        cur = self._conn.cursor()
        cur.execute(
            """
            DELETE FROM job_history
            WHERE COALESCE(finished_at, updated_at) < ?
            """,
            (cutoff_iso,),
        )
        self._conn.commit()
        return cur.rowcount

    def _stats_sync(self, days: int) -> HistoryStats:
        now = _utcnow()
        start = now - timedelta(days=days)
        start_iso = start.isoformat()
        cur = self._conn.cursor()
        rows = cur.execute(
            """
            SELECT *
            FROM job_history
            WHERE COALESCE(finished_at, updated_at) >= ?
            """,
            (start_iso,),
        ).fetchall()

        totals_by_state: Dict[str, int] = {}
        per_addon: Dict[str, Dict[str, Any]] = {}
        queue_waits: List[float] = []

        for row in rows:
            state = row["state"] or "unknown"
            totals_by_state[state] = totals_by_state.get(state, 0) + 1

            addon_id = row["addon_id"] or "unknown"
            stats = per_addon.setdefault(
                addon_id,
                {
                    "addon_id": addon_id,
                    "count": 0,
                    "states": {},
                    "durations_s": [],
                    "queue_waits_s": [],
                },
            )
            stats["count"] += 1
            states = stats["states"]
            states[state] = states.get(state, 0) + 1

            leased_at = _from_iso(row["leased_at"])
            finished_at = _from_iso(row["finished_at"])
            if leased_at and finished_at:
                stats["durations_s"].append((finished_at - leased_at).total_seconds())
            created_at = _from_iso(row["created_at"])
            if created_at and leased_at:
                wait_s = (leased_at - created_at).total_seconds()
                queue_waits.append(wait_s)
                stats["queue_waits_s"].append(wait_s)

        addons_out: List[Dict[str, Any]] = []
        for addon_id, stats in sorted(per_addon.items(), key=lambda kv: kv[0]):
            durations = sorted(stats["durations_s"])
            avg = sum(durations) / len(durations) if durations else None
            p95 = None
            if durations:
                idx = max(0, int(len(durations) * 0.95) - 1)
                p95 = durations[idx]
            queue_waits_addon = stats.get("queue_waits_s", [])
            avg_queue_wait = sum(queue_waits_addon) / len(queue_waits_addon) if queue_waits_addon else None
            addons_out.append(
                {
                    "addon_id": addon_id,
                    "count": stats["count"],
                    "states": stats["states"],
                    "avg_runtime_s": avg,
                    "p95_runtime_s": p95,
                    "avg_queue_wait_s": avg_queue_wait,
                }
            )

        completed = totals_by_state.get("completed", 0)
        failed = totals_by_state.get("failed", 0)
        expired = totals_by_state.get("expired", 0)
        denom = completed + failed + expired
        success_rate = (completed / denom) if denom > 0 else None
        avg_queue_wait = sum(queue_waits) / len(queue_waits) if queue_waits else None

        return HistoryStats(
            range_start=start,
            range_end=now,
            total=len(rows),
            totals_by_state=totals_by_state,
            success_rate=success_rate,
            avg_queue_wait_s=avg_queue_wait,
            addons=addons_out,
        )

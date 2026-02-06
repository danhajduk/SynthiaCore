# backend/app/system/scheduler/queue_persist.py
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .models import JobIntent, QueueJobState, _coerce_priority, _coerce_queue_state


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt_from_iso(val: str | None) -> Optional[datetime]:
    if not val:
        return None
    return datetime.fromisoformat(val)


DDL = """
CREATE TABLE IF NOT EXISTS scheduler_jobs (
  job_id TEXT PRIMARY KEY,
  addon_id TEXT NOT NULL,
  job_type TEXT NOT NULL,
  cost_units INTEGER NOT NULL,
  priority TEXT NOT NULL,
  constraints_json TEXT,
  expected_duration_sec INTEGER,
  payload_json TEXT,
  time_sensitive INTEGER,
  earliest_start_at TEXT,
  deadline_at TEXT,
  max_runtime_sec INTEGER,
  tags_json TEXT,
  state TEXT NOT NULL,
  attempts INTEGER NOT NULL,
  next_earliest_start_at TEXT,
  lease_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduler_job_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  job_id TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT,
  reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_scheduler_jobs_state ON scheduler_jobs(state);
CREATE INDEX IF NOT EXISTS idx_scheduler_jobs_updated ON scheduler_jobs(updated_at);
CREATE INDEX IF NOT EXISTS idx_scheduler_job_events_job ON scheduler_job_events(job_id);
"""


class QueuePersistStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()
        self._init_db()

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(DDL)
        self._conn.commit()

    async def upsert_job(self, job: JobIntent) -> None:
        await self._run(self._upsert_job_sync, job)

    async def record_event(
        self,
        job_id: str,
        from_state: QueueJobState | None,
        to_state: QueueJobState | None,
        reason: Optional[str] = None,
    ) -> None:
        await self._run(self._record_event_sync, job_id, from_state, to_state, reason)

    async def load_jobs(self) -> List[JobIntent]:
        return await self._run(self._load_jobs_sync)

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    def _upsert_job_sync(self, job: JobIntent) -> None:
        self._conn.execute(
            """
            INSERT INTO scheduler_jobs (
              job_id, addon_id, job_type, cost_units, priority,
              constraints_json, expected_duration_sec, payload_json, time_sensitive,
              earliest_start_at, deadline_at, max_runtime_sec, tags_json,
              state, attempts, next_earliest_start_at, lease_id,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
              addon_id=excluded.addon_id,
              job_type=excluded.job_type,
              cost_units=excluded.cost_units,
              priority=excluded.priority,
              constraints_json=excluded.constraints_json,
              expected_duration_sec=excluded.expected_duration_sec,
              payload_json=excluded.payload_json,
              time_sensitive=excluded.time_sensitive,
              earliest_start_at=excluded.earliest_start_at,
              deadline_at=excluded.deadline_at,
              max_runtime_sec=excluded.max_runtime_sec,
              tags_json=excluded.tags_json,
              state=excluded.state,
              attempts=excluded.attempts,
              next_earliest_start_at=excluded.next_earliest_start_at,
              lease_id=excluded.lease_id,
              updated_at=excluded.updated_at
            """,
            (
                job.job_id,
                job.addon_id,
                job.job_type,
                int(job.cost_units),
                str(job.priority),
                json.dumps(job.constraints or {}),
                job.expected_duration_sec,
                json.dumps(job.payload or {}),
                1 if job.time_sensitive else 0,
                job.earliest_start_at.isoformat() if job.earliest_start_at else None,
                job.deadline_at.isoformat() if job.deadline_at else None,
                job.max_runtime_sec,
                json.dumps(job.tags or []),
                str(job.state),
                int(job.attempts),
                job.next_earliest_start_at.isoformat() if job.next_earliest_start_at else None,
                job.lease_id,
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
            ),
        )
        self._conn.commit()

    def _record_event_sync(
        self,
        job_id: str,
        from_state: QueueJobState | None,
        to_state: QueueJobState | None,
        reason: Optional[str],
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO scheduler_job_events (ts, job_id, from_state, to_state, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                _utcnow_iso(),
                job_id,
                str(from_state) if from_state else None,
                str(to_state) if to_state else None,
                reason,
            ),
        )
        self._conn.commit()

    def _load_jobs_sync(self) -> List[JobIntent]:
        rows = self._conn.execute("SELECT * FROM scheduler_jobs").fetchall()
        out: List[JobIntent] = []
        for row in rows:
            out.append(
                JobIntent(
                    job_id=row["job_id"],
                    addon_id=row["addon_id"],
                    job_type=row["job_type"],
                    cost_units=int(row["cost_units"]),
                    priority=_coerce_priority(row["priority"]),
                    constraints=json.loads(row["constraints_json"] or "{}"),
                    expected_duration_sec=row["expected_duration_sec"],
                    payload=json.loads(row["payload_json"] or "{}"),
                    time_sensitive=bool(row["time_sensitive"]),
                    earliest_start_at=_dt_from_iso(row["earliest_start_at"]),
                    deadline_at=_dt_from_iso(row["deadline_at"]),
                    max_runtime_sec=row["max_runtime_sec"],
                    tags=json.loads(row["tags_json"] or "[]"),
                    state=_coerce_queue_state(row["state"]),
                    attempts=int(row["attempts"]),
                    next_earliest_start_at=_dt_from_iso(row["next_earliest_start_at"]),
                    lease_id=row["lease_id"],
                    created_at=_dt_from_iso(row["created_at"]) or datetime.now(timezone.utc),
                    updated_at=_dt_from_iso(row["updated_at"]) or datetime.now(timezone.utc),
                )
            )
        return out

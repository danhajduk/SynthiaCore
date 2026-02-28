from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime) -> str:
    return dt.isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


class UsageTelemetryStore:
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
            CREATE TABLE IF NOT EXISTS telemetry_usage (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              service TEXT NOT NULL,
              consumer_addon_id TEXT NOT NULL,
              grant_id TEXT,
              usage_units REAL NOT NULL,
              request_count INTEGER NOT NULL,
              period_start TEXT,
              period_end TEXT,
              reported_at TEXT NOT NULL,
              metadata_json TEXT NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_service ON telemetry_usage(service)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_consumer ON telemetry_usage(consumer_addon_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_grant ON telemetry_usage(grant_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_reported ON telemetry_usage(reported_at)")
        self._conn.commit()

    async def record_usage(self, item: dict[str, Any]) -> dict[str, Any]:
        return await self._run(self._record_usage_sync, item)

    async def list_usage(
        self,
        limit: int = 100,
        service: str | None = None,
        consumer_addon_id: str | None = None,
        grant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._run(self._list_usage_sync, limit, service, consumer_addon_id, grant_id)

    async def usage_stats(self, days: int = 30) -> dict[str, Any]:
        return await self._run(self._usage_stats_sync, days)

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    def _record_usage_sync(self, item: dict[str, Any]) -> dict[str, Any]:
        reported_at = _to_iso(_utcnow())
        self._conn.execute(
            """
            INSERT INTO telemetry_usage (
              service, consumer_addon_id, grant_id, usage_units, request_count,
              period_start, period_end, reported_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["service"],
                item["consumer_addon_id"],
                item.get("grant_id"),
                float(item.get("usage_units", 0.0)),
                int(item.get("request_count", 0)),
                item.get("period_start"),
                item.get("period_end"),
                reported_at,
                json.dumps(item.get("metadata", {})),
            ),
        )
        row_id = int(self._conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        self._conn.commit()
        return {
            "id": row_id,
            "service": item["service"],
            "consumer_addon_id": item["consumer_addon_id"],
            "grant_id": item.get("grant_id"),
            "usage_units": float(item.get("usage_units", 0.0)),
            "request_count": int(item.get("request_count", 0)),
            "period_start": item.get("period_start"),
            "period_end": item.get("period_end"),
            "reported_at": reported_at,
            "metadata": item.get("metadata", {}),
        }

    def _list_usage_sync(
        self,
        limit: int,
        service: str | None,
        consumer_addon_id: str | None,
        grant_id: str | None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(1000, int(limit)))
        clauses: list[str] = []
        params: list[Any] = []
        if service:
            clauses.append("service = ?")
            params.append(service)
        if consumer_addon_id:
            clauses.append("consumer_addon_id = ?")
            params.append(consumer_addon_id)
        if grant_id:
            clauses.append("grant_id = ?")
            params.append(grant_id)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT *
            FROM telemetry_usage
            {where_sql}
            ORDER BY reported_at DESC, id DESC
            LIMIT ?
        """
        params.append(limit)
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "id": int(row["id"]),
                    "service": row["service"],
                    "consumer_addon_id": row["consumer_addon_id"],
                    "grant_id": row["grant_id"],
                    "usage_units": float(row["usage_units"]),
                    "request_count": int(row["request_count"]),
                    "period_start": row["period_start"],
                    "period_end": row["period_end"],
                    "reported_at": row["reported_at"],
                    "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                }
            )
        return out

    def _usage_stats_sync(self, days: int) -> dict[str, Any]:
        days = max(1, min(365, int(days)))
        cutoff = _to_iso(_utcnow() - timedelta(days=days))

        totals = self._conn.execute(
            """
            SELECT
              COALESCE(SUM(usage_units), 0.0) as usage_units_sum,
              COALESCE(SUM(request_count), 0) as request_count_sum,
              COUNT(*) as reports
            FROM telemetry_usage
            WHERE reported_at >= ?
            """,
            (cutoff,),
        ).fetchone()

        by_service_rows = self._conn.execute(
            """
            SELECT service, COUNT(*) as reports, COALESCE(SUM(usage_units), 0.0) as usage_units_sum,
                   COALESCE(SUM(request_count), 0) as request_count_sum
            FROM telemetry_usage
            WHERE reported_at >= ?
            GROUP BY service
            ORDER BY usage_units_sum DESC, reports DESC
            """,
            (cutoff,),
        ).fetchall()

        by_consumer_rows = self._conn.execute(
            """
            SELECT consumer_addon_id, COUNT(*) as reports, COALESCE(SUM(usage_units), 0.0) as usage_units_sum,
                   COALESCE(SUM(request_count), 0) as request_count_sum
            FROM telemetry_usage
            WHERE reported_at >= ?
            GROUP BY consumer_addon_id
            ORDER BY usage_units_sum DESC, reports DESC
            """,
            (cutoff,),
        ).fetchall()

        by_grant_rows = self._conn.execute(
            """
            SELECT grant_id, COUNT(*) as reports, COALESCE(SUM(usage_units), 0.0) as usage_units_sum,
                   COALESCE(SUM(request_count), 0) as request_count_sum
            FROM telemetry_usage
            WHERE reported_at >= ? AND grant_id IS NOT NULL AND grant_id != ''
            GROUP BY grant_id
            ORDER BY usage_units_sum DESC, reports DESC
            """,
            (cutoff,),
        ).fetchall()

        return {
            "range_days": days,
            "totals": {
                "reports": int(totals["reports"]),
                "usage_units_sum": float(totals["usage_units_sum"]),
                "request_count_sum": int(totals["request_count_sum"]),
            },
            "by_service": [
                {
                    "service": row["service"],
                    "reports": int(row["reports"]),
                    "usage_units_sum": float(row["usage_units_sum"]),
                    "request_count_sum": int(row["request_count_sum"]),
                }
                for row in by_service_rows
            ],
            "by_consumer": [
                {
                    "consumer_addon_id": row["consumer_addon_id"],
                    "reports": int(row["reports"]),
                    "usage_units_sum": float(row["usage_units_sum"]),
                    "request_count_sum": int(row["request_count_sum"]),
                }
                for row in by_consumer_rows
            ],
            "by_grant": [
                {
                    "grant_id": row["grant_id"],
                    "reports": int(row["reports"]),
                    "usage_units_sum": float(row["usage_units_sum"]),
                    "request_count_sum": int(row["request_count_sum"]),
                }
                for row in by_grant_rows
            ],
        }

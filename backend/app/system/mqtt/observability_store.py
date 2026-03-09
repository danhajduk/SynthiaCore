from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MqttObservabilityStore:
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
            CREATE TABLE IF NOT EXISTS mqtt_observability_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_type TEXT NOT NULL,
              source TEXT NOT NULL,
              severity TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mqtt_obsv_created ON mqtt_observability_events(created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mqtt_obsv_event ON mqtt_observability_events(event_type)")
        self._conn.commit()

    async def append_event(
        self,
        *,
        event_type: str,
        source: str,
        severity: str = "info",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._run(self._append_event_sync, event_type, source, severity, metadata or {})

    async def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self._run(self._list_events_sync, limit)

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    def _append_event_sync(self, event_type: str, source: str, severity: str, metadata: dict[str, Any]) -> dict[str, Any]:
        created_at = _utcnow_iso()
        self._conn.execute(
            """
            INSERT INTO mqtt_observability_events (event_type, source, severity, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_type, source, severity, json.dumps(metadata, sort_keys=True), created_at),
        )
        row_id = int(self._conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        self._conn.commit()
        return {
            "id": row_id,
            "event_type": event_type,
            "source": source,
            "severity": severity,
            "metadata": metadata,
            "created_at": created_at,
        }

    def _list_events_sync(self, limit: int) -> list[dict[str, Any]]:
        selected = max(1, min(1000, int(limit)))
        rows = self._conn.execute(
            """
            SELECT id, event_type, source, severity, metadata_json, created_at
            FROM mqtt_observability_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (selected,),
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "event_type": row["event_type"],
                "source": row["source"],
                "severity": row["severity"],
                "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                "created_at": row["created_at"],
            }
            for row in rows
        ]

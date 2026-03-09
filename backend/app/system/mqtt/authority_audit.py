from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MqttAuthorityAuditStore:
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
            CREATE TABLE IF NOT EXISTS mqtt_authority_audit (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_type TEXT NOT NULL,
              status TEXT NOT NULL,
              message TEXT,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mqtt_audit_created ON mqtt_authority_audit(created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mqtt_audit_event ON mqtt_authority_audit(event_type)")
        self._conn.commit()

    async def append_event(self, *, event_type: str, status: str, message: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._run(self._append_event_sync, event_type, status, message, payload or {})

    async def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self._run(self._list_events_sync, limit)

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    def _append_event_sync(self, event_type: str, status: str, message: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        created_at = _utcnow_iso()
        self._conn.execute(
            """
            INSERT INTO mqtt_authority_audit (event_type, status, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_type, status, message, json.dumps(payload, sort_keys=True), created_at),
        )
        row_id = int(self._conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        self._conn.commit()
        return {
            "id": row_id,
            "event_type": event_type,
            "status": status,
            "message": message,
            "payload": payload,
            "created_at": created_at,
        }

    def _list_events_sync(self, limit: int) -> list[dict[str, Any]]:
        selected = max(1, min(1000, int(limit)))
        rows = self._conn.execute(
            """
            SELECT id, event_type, status, message, payload_json, created_at
            FROM mqtt_authority_audit
            ORDER BY id DESC
            LIMIT ?
            """,
            (selected,),
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "event_type": row["event_type"],
                "status": row["status"],
                "message": row["message"],
                "payload": json.loads(row["payload_json"]) if row["payload_json"] else {},
                "created_at": row["created_at"],
            }
            for row in rows
        ]

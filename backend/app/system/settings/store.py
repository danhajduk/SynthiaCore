# backend/app/system/settings/store.py
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SettingsStore:
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
            CREATE TABLE IF NOT EXISTS app_settings (
              key TEXT PRIMARY KEY,
              value_json TEXT,
              updated_at TEXT
            )
            """
        )
        self._conn.commit()

    async def get_all(self) -> Dict[str, Any]:
        return await self._run(self._get_all_sync)

    async def get(self, key: str) -> Optional[Any]:
        return await self._run(self._get_sync, key)

    async def set(self, key: str, value: Any) -> None:
        await self._run(self._set_sync, key, value)

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    def _get_all_sync(self) -> Dict[str, Any]:
        cur = self._conn.cursor()
        rows = cur.execute("SELECT key, value_json FROM app_settings").fetchall()
        out: Dict[str, Any] = {}
        for row in rows:
            try:
                out[row["key"]] = json.loads(row["value_json"])
            except Exception:
                out[row["key"]] = None
        return out

    def _get_sync(self, key: str) -> Optional[Any]:
        cur = self._conn.cursor()
        row = cur.execute("SELECT value_json FROM app_settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["value_json"])
        except Exception:
            return None

    def _set_sync(self, key: str, value: Any) -> None:
        self._conn.execute(
            """
            INSERT INTO app_settings (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value_json=excluded.value_json,
              updated_at=excluded.updated_at
            """,
            (key, json.dumps(value), _utcnow_iso()),
        )
        self._conn.commit()

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

DB_PATH = Path("data/system_stats.sqlite3")

DDL = """
CREATE TABLE IF NOT EXISTS stats_minute (
  ts REAL PRIMARY KEY,
  busy REAL NOT NULL,
  snapshot_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stats_minute_ts ON stats_minute(ts);
"""

class StatsStore:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.executescript(DDL)
        self.conn.commit()

    def insert_minute(self, ts: float, busy: float, snapshot: Dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO stats_minute(ts, busy, snapshot_json) VALUES (?, ?, ?)",
            (ts, busy, json.dumps(snapshot, separators=(",", ":"))),
        )
        self.conn.commit()

    def prune_older_than(self, seconds: int) -> None:
        cutoff = time.time() - seconds
        self.conn.execute("DELETE FROM stats_minute WHERE ts < ?", (cutoff,))
        self.conn.commit()

    def last_n(self, n: int = 1440) -> List[Tuple[float, float]]:
        cur = self.conn.execute(
            "SELECT ts, busy FROM stats_minute ORDER BY ts DESC LIMIT ?",
            (n,),
        )
        rows = cur.fetchall()
        rows.reverse()
        return rows

    def avg_since(self, since_ts: float) -> float:
        cur = self.conn.execute(
            "SELECT AVG(busy) FROM stats_minute WHERE ts >= ?",
            (since_ts,),
        )
        val = cur.fetchone()[0]
        return float(val) if val is not None else 0.0

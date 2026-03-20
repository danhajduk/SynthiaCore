from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

from app.system.security import redact_secrets


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditLogStore:
    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = asyncio.Lock()

    async def record(
        self,
        *,
        event_type: str,
        actor_role: str,
        actor_id: str,
        details: dict[str, Any],
    ) -> None:
        line = self._build_line(
            event_type=event_type,
            actor_role=actor_role,
            actor_id=actor_id,
            details=details,
        )
        async with self._lock:
            await asyncio.to_thread(self._append_line, line)

    def record_sync(
        self,
        *,
        event_type: str,
        actor_role: str,
        actor_id: str,
        details: dict[str, Any],
    ) -> None:
        self._append_line(
            self._build_line(
                event_type=event_type,
                actor_role=actor_role,
                actor_id=actor_id,
                details=details,
            )
        )

    def _build_line(
        self,
        *,
        event_type: str,
        actor_role: str,
        actor_id: str,
        details: dict[str, Any],
    ) -> str:
        row = {
            "ts": _utcnow_iso(),
            "event_type": event_type,
            "actor_role": actor_role,
            "actor_id": actor_id,
            "details": redact_secrets(details),
        }
        return json.dumps(row, sort_keys=True)

    def _append_line(self, line: str) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

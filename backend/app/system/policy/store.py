from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PolicyStore:
    def __init__(self, grants_path: str, revocations_path: str) -> None:
        self.grants_path = grants_path
        self.revocations_path = revocations_path
        os.makedirs(os.path.dirname(grants_path), exist_ok=True)
        os.makedirs(os.path.dirname(revocations_path), exist_ok=True)
        self._lock = asyncio.Lock()

    async def list_grants(self, service: str | None = None) -> list[dict[str, Any]]:
        async with self._lock:
            data = await asyncio.to_thread(self._read_json, self.grants_path, [])
        if service:
            return [g for g in data if str(g.get("service")) == service]
        return data

    async def upsert_grant(self, grant: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            grants = await asyncio.to_thread(self._read_json, self.grants_path, [])
            grant_id = str(grant["grant_id"])
            found = False
            for idx, item in enumerate(grants):
                if str(item.get("grant_id")) == grant_id:
                    merged = {**item, **grant}
                    merged["updated_at"] = _utcnow_iso()
                    grants[idx] = merged
                    grant = merged
                    found = True
                    break
            if not found:
                grant = {**grant, "created_at": _utcnow_iso(), "updated_at": _utcnow_iso()}
                grants.append(grant)
            await asyncio.to_thread(self._write_json, self.grants_path, grants)
            return grant

    async def list_revocations(self) -> list[dict[str, Any]]:
        async with self._lock:
            return await asyncio.to_thread(self._read_json, self.revocations_path, [])

    async def upsert_revocation(self, item: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            rows = await asyncio.to_thread(self._read_json, self.revocations_path, [])
            revocation_id = str(item["id"])
            found = False
            for idx, existing in enumerate(rows):
                if str(existing.get("id")) == revocation_id:
                    merged = {**existing, **item}
                    merged["updated_at"] = _utcnow_iso()
                    rows[idx] = merged
                    item = merged
                    found = True
                    break
            if not found:
                item = {**item, "created_at": _utcnow_iso(), "updated_at": _utcnow_iso()}
                rows.append(item)
            await asyncio.to_thread(self._write_json, self.revocations_path, rows)
            return item

    @staticmethod
    def _read_json(path: str, default: Any) -> Any:
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, type(default)) else default
        except Exception:
            return default

    @staticmethod
    def _write_json(path: str, value: Any) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, sort_keys=True)

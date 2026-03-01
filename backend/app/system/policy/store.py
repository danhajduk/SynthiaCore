from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any


GRANT_LIMIT_KEYS = ("max_requests", "max_tokens", "max_cost_cents", "max_bytes")


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
            normalized, changed = self._normalize_grants(data)
            if changed:
                await asyncio.to_thread(self._write_json, self.grants_path, normalized)
        if service:
            return [g for g in normalized if str(g.get("service")) == service]
        return normalized

    async def upsert_grant(self, grant: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            grants = await asyncio.to_thread(self._read_json, self.grants_path, [])
            grants, _ = self._normalize_grants(grants)
            grant = self._normalize_grant(grant)
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

    @classmethod
    def _normalize_grants(cls, rows: Any) -> tuple[list[dict[str, Any]], bool]:
        if not isinstance(rows, list):
            return [], True
        changed = False
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                changed = True
                continue
            fixed = cls._normalize_grant(row)
            if fixed != row:
                changed = True
            normalized.append(fixed)
        return normalized, changed

    @classmethod
    def _normalize_grant(cls, item: dict[str, Any]) -> dict[str, Any]:
        out = dict(item)
        out["limits"] = cls._normalize_limits(out.get("limits"))
        return out

    @staticmethod
    def _normalize_limits(raw: Any) -> dict[str, int]:
        if not isinstance(raw, dict):
            return {}

        data = dict(raw)
        if data.get("max_tokens") is None and data.get("max_units") is not None:
            data["max_tokens"] = data.get("max_units")
        if data.get("max_requests") is None and data.get("burst") is not None:
            data["max_requests"] = data.get("burst")

        limits: dict[str, int] = {}
        for key in GRANT_LIMIT_KEYS:
            value = data.get(key)
            if value is None:
                continue
            try:
                limits[key] = int(value)
            except (TypeError, ValueError):
                continue
        return limits

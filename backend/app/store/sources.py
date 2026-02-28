from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

OFFICIAL_SOURCE_ID = "official"
OFFICIAL_SOURCE_BASE_URL = "https://raw.githubusercontent.com/danhajduk/Synthia-Addon-Catalog/main"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StoreSource(BaseModel):
    id: str = Field(..., min_length=1)
    type: Literal["github_raw"] = "github_raw"
    base_url: str = Field(..., min_length=1)
    enabled: bool = True
    refresh_seconds: int = Field(default=300, ge=10, le=86400)
    last_refresh_requested_at: str | None = None


class StoreSourcesStore:
    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = asyncio.Lock()
        self._ensure_defaults()

    async def list_sources(self) -> list[StoreSource]:
        async with self._lock:
            raw = await asyncio.to_thread(self._read_sync)
            return [StoreSource.model_validate(x) for x in raw]

    async def upsert_source(self, source: StoreSource) -> StoreSource:
        async with self._lock:
            saved = await asyncio.to_thread(self._upsert_sync, source.model_dump(mode="json"))
            return StoreSource.model_validate(saved)

    async def delete_source(self, source_id: str) -> bool:
        async with self._lock:
            return await asyncio.to_thread(self._delete_sync, source_id)

    async def mark_refresh(self, source_id: str) -> StoreSource:
        async with self._lock:
            saved = await asyncio.to_thread(self._mark_refresh_sync, source_id)
            return StoreSource.model_validate(saved)

    def _default_sources(self) -> list[dict]:
        return [
            StoreSource(
                id=OFFICIAL_SOURCE_ID,
                type="github_raw",
                base_url=OFFICIAL_SOURCE_BASE_URL,
                enabled=True,
                refresh_seconds=300,
            ).model_dump(mode="json")
        ]

    def _ensure_defaults(self) -> None:
        if not os.path.exists(self.path):
            self._write_sync(self._default_sources())
            return
        data = self._read_sync()
        if not any(str(x.get("id", "")).strip() == OFFICIAL_SOURCE_ID for x in data):
            data.append(self._default_sources()[0])
            self._write_sync(data)

    def _read_sync(self) -> list[dict]:
        if not os.path.exists(self.path):
            return self._default_sources()
        try:
            raw = json.loads(Path(self.path).read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return self._default_sources()
            out: list[dict] = []
            for item in raw:
                if isinstance(item, dict):
                    out.append(item)
            return out or self._default_sources()
        except Exception:
            return self._default_sources()

    def _write_sync(self, value: list[dict]) -> None:
        Path(self.path).write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")

    def _upsert_sync(self, source: dict) -> dict:
        data = self._read_sync()
        src_id = str(source.get("id", "")).strip()
        if not src_id:
            raise ValueError("source_id_required")
        source["id"] = src_id
        replaced = False
        for idx, item in enumerate(data):
            if str(item.get("id", "")).strip() == src_id:
                data[idx] = source
                replaced = True
                break
        if not replaced:
            data.append(source)
        self._write_sync(data)
        return source

    def _delete_sync(self, source_id: str) -> bool:
        sid = source_id.strip()
        if sid == OFFICIAL_SOURCE_ID:
            raise ValueError("official_source_cannot_be_deleted")
        data = self._read_sync()
        kept = [x for x in data if str(x.get("id", "")).strip() != sid]
        existed = len(kept) != len(data)
        if existed:
            self._write_sync(kept)
        return existed

    def _mark_refresh_sync(self, source_id: str) -> dict:
        sid = source_id.strip()
        data = self._read_sync()
        for item in data:
            if str(item.get("id", "")).strip() == sid:
                item["last_refresh_requested_at"] = _utcnow_iso()
                self._write_sync(data)
                return item
        raise ValueError("source_not_found")

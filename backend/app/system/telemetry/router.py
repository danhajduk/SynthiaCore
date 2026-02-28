from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from .store import UsageTelemetryStore


class UsageIngestRequest(BaseModel):
    service: str = Field(..., min_length=1)
    consumer_addon_id: str = Field(..., min_length=1)
    grant_id: str | None = None
    usage_units: float = Field(default=0.0, ge=0.0)
    request_count: int = Field(default=0, ge=0)
    period_start: str | None = None
    period_end: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_telemetry_router(store: UsageTelemetryStore) -> APIRouter:
    router = APIRouter()

    @router.post("/usage")
    async def ingest_usage(body: UsageIngestRequest):
        saved = await store.record_usage(body.model_dump(mode="json"))
        return {"ok": True, "usage": saved}

    @router.get("/usage")
    async def usage_history(
        limit: int = Query(default=100, ge=1, le=1000),
        service: str | None = Query(default=None),
        consumer_addon_id: str | None = Query(default=None),
        grant_id: str | None = Query(default=None),
    ):
        rows = await store.list_usage(
            limit=limit,
            service=service,
            consumer_addon_id=consumer_addon_id,
            grant_id=grant_id,
        )
        return {"ok": True, "items": rows}

    @router.get("/usage/stats")
    async def usage_stats(days: int = Query(default=30, ge=1, le=365)):
        return {"ok": True, "stats": await store.usage_stats(days=days)}

    return router

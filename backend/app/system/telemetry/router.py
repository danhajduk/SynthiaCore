from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.system.auth import ServiceTokenClaims, ServiceTokenKeyStore, require_service_token
from app.system.security import AuthRole
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


def build_telemetry_router(store: UsageTelemetryStore, key_store: ServiceTokenKeyStore) -> APIRouter:
    router = APIRouter()
    require_write_scope = require_service_token(
        key_store=key_store,
        audience="synthia-core",
        scopes=["telemetry.write"],
    )

    @router.post("/usage")
    async def ingest_usage(
        body: UsageIngestRequest,
        claims: ServiceTokenClaims = Depends(require_write_scope),
    ):
        saved = await store.record_usage(body.model_dump(mode="json"))
        return {"ok": True, "usage": saved, "role": AuthRole.service.value, "sub": claims.sub}

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

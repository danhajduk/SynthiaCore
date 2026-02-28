from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.admin import require_admin_token
from app.system.mqtt import MqttManager
from .store import PolicyStore


class GrantLimits(BaseModel):
    max_requests: int | None = None
    max_units: int | None = None
    burst: int | None = None


class GrantUpsertRequest(BaseModel):
    grant_id: str = Field(..., min_length=1)
    consumer_addon_id: str = Field(..., min_length=1)
    service: str = Field(..., min_length=1)
    period_start: str
    period_end: str
    limits: GrantLimits = Field(default_factory=GrantLimits)
    status: str = Field(default="active")


class RevocationUpsertRequest(BaseModel):
    id: str = Field(..., min_length=1)
    grant_id: str | None = None
    service: str | None = None
    reason: str = ""
    status: str = "revoked"


def build_policy_router(store: PolicyStore, mqtt_manager: MqttManager) -> APIRouter:
    router = APIRouter()

    @router.get("/grants")
    async def get_grants(service: str | None = Query(default=None)):
        return {"ok": True, "grants": await store.list_grants(service=service)}

    @router.post("/grants")
    async def upsert_grant(body: GrantUpsertRequest, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token)
        grant = await store.upsert_grant(body.model_dump(mode="json"))
        topic = f"synthia/policy/grants/{grant['service']}"
        publish = await mqtt_manager.publish(topic=topic, payload=grant, retain=True, qos=1)
        return {"ok": True, "grant": grant, "mqtt": publish}

    @router.get("/revocations")
    async def get_revocations():
        return {"ok": True, "revocations": await store.list_revocations()}

    @router.post("/revocations")
    async def upsert_revocation(body: RevocationUpsertRequest, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token)
        item = await store.upsert_revocation(body.model_dump(mode="json"))
        topic = f"synthia/policy/revocations/{item['id']}"
        publish = await mqtt_manager.publish(topic=topic, payload=item, retain=True, qos=1)
        return {"ok": True, "revocation": item, "mqtt": publish}

    return router

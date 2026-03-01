from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.admin import require_admin_token
from app.system.audit import AuditLogStore
from app.system.mqtt import MqttManager
from app.system.security import AuthRole
from .store import PolicyStore


class GrantLimits(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_requests: int | None = None
    max_tokens: int | None = None
    max_cost_cents: int | None = None
    max_bytes: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if data.get("max_tokens") is None and data.get("max_units") is not None:
            data["max_tokens"] = data.get("max_units")
        if data.get("max_requests") is None and data.get("burst") is not None:
            data["max_requests"] = data.get("burst")
        data.pop("max_units", None)
        data.pop("burst", None)
        return data


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


def build_policy_router(
    store: PolicyStore,
    mqtt_manager: MqttManager,
    audit_store: AuditLogStore | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/grants")
    async def get_grants(service: str | None = Query(default=None)):
        return {"ok": True, "grants": await store.list_grants(service=service)}

    @router.post("/grants")
    async def upsert_grant(
        body: GrantUpsertRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        grant = await store.upsert_grant(body.model_dump(mode="json"))
        topic = f"synthia/policy/grants/{grant['service']}"
        publish = await mqtt_manager.publish(topic=topic, payload=grant, retain=True, qos=1)
        if audit_store is not None:
            await audit_store.record(
                event_type="grant_changed",
                actor_role=AuthRole.admin.value,
                actor_id="admin_token",
                details={"grant_id": grant["grant_id"], "service": grant["service"], "status": grant["status"]},
            )
        return {"ok": True, "grant": grant, "mqtt": publish}

    @router.get("/revocations")
    async def get_revocations():
        return {"ok": True, "revocations": await store.list_revocations()}

    @router.post("/revocations")
    async def upsert_revocation(
        body: RevocationUpsertRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        item = await store.upsert_revocation(body.model_dump(mode="json"))
        topic = f"synthia/policy/revocations/{item['id']}"
        publish = await mqtt_manager.publish(topic=topic, payload=item, retain=True, qos=1)
        if audit_store is not None:
            await audit_store.record(
                event_type="revocation_changed",
                actor_role=AuthRole.admin.value,
                actor_id="admin_token",
                details={"id": item["id"], "grant_id": item.get("grant_id"), "service": item.get("service")},
            )
        return {"ok": True, "revocation": item, "mqtt": publish}

    return router

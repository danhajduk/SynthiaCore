# backend/app/system/settings/router.py
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Any

from app.api.admin import require_admin_token
from app.system.audit import AuditLogStore
from app.system.security import AuthRole
from .store import SettingsStore


class SetSettingRequest(BaseModel):
    value: Any


def build_settings_router(store: SettingsStore, audit_store: AuditLogStore | None = None) -> APIRouter:
    router = APIRouter()

    @router.get("/settings")
    async def get_all():
        return {"ok": True, "settings": await store.get_all()}

    @router.get("/settings/{key}")
    async def get_one(key: str):
        val = await store.get(key)
        if val is None:
            raise HTTPException(status_code=404, detail="setting_not_found")
        return {"ok": True, "key": key, "value": val}

    @router.put("/settings/{key}")
    async def set_one(key: str, body: SetSettingRequest, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token)
        await store.set(key, body.value)
        if audit_store is not None:
            await audit_store.record(
                event_type="privileged_config_update",
                actor_role=AuthRole.admin.value,
                actor_id="admin_token",
                details={"key": key, "value_type": type(body.value).__name__},
            )
        return {"ok": True, "key": key, "value": body.value}

    return router

# backend/app/system/settings/router.py
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from typing import Any

from app.api.admin import require_admin_token
from app.system.audit import AuditLogStore
from app.system.platform_identity import load_platform_identity
from app.system.security import AuthRole
from .store import SettingsStore


class SetSettingRequest(BaseModel):
    value: Any


class PlatformIdentityResponse(BaseModel):
    ok: bool = True
    core_id: str
    platform_name: str
    platform_short: str
    platform_domain: str
    core_name: str
    supervisor_name: str
    nodes_name: str
    addons_name: str
    docs_name: str
    legacy_internal_namespace: str
    legacy_compatibility_note: str
    public_hostname: str
    public_ui_hostname: str
    public_api_hostname: str


def build_settings_router(store: SettingsStore, audit_store: AuditLogStore | None = None) -> APIRouter:
    router = APIRouter()

    @router.get("/platform", response_model=PlatformIdentityResponse)
    async def get_platform_identity():
        identity = await load_platform_identity(store)
        return PlatformIdentityResponse(**{"ok": True, **identity.to_dict()})

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
    async def set_one(
        key: str,
        body: SetSettingRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
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

# backend/app/system/settings/router.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any

from .store import SettingsStore


class SetSettingRequest(BaseModel):
    value: Any


def build_settings_router(store: SettingsStore) -> APIRouter:
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
    async def set_one(key: str, body: SetSettingRequest):
        await store.set(key, body.value)
        return {"ok": True, "key": key, "value": body.value}

    return router

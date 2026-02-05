from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..addons.registry import AddonRegistry, list_addons


class SetAddonEnabledRequest(BaseModel):
    enabled: bool

def build_system_router(registry: AddonRegistry) -> APIRouter:
    router = APIRouter()

    @router.get("/addons")
    def get_addons():
        return list_addons(registry)

    @router.post("/addons/{addon_id}/enable")
    def set_addon_enabled(addon_id: str, body: SetAddonEnabledRequest):
        if addon_id not in registry.addons:
            raise HTTPException(status_code=404, detail="addon_not_found")
        registry.set_enabled(addon_id, body.enabled)
        return {"ok": True, "id": addon_id, "enabled": registry.is_enabled(addon_id)}

    @router.get("/addons/errors")
    def get_addon_errors():
        # Helpful when something fails to import but you still want the server up.
        return registry.errors

    return router

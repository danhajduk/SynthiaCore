from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from ..addons.registry import AddonRegistry, list_addons
from ..system.runtime import StandaloneRuntimeService
from .admin import require_admin_token


class SetAddonEnabledRequest(BaseModel):
    enabled: bool

def build_system_router(
    registry: AddonRegistry,
    runtime_service: StandaloneRuntimeService | None = None,
) -> APIRouter:
    router = APIRouter()
    runtime = runtime_service or StandaloneRuntimeService()

    @router.get("/addons")
    def get_addons():
        return list_addons(registry)

    @router.post("/addons/{addon_id}/enable")
    def set_addon_enabled(addon_id: str, body: SetAddonEnabledRequest):
        if not registry.has_addon(addon_id):
            raise HTTPException(status_code=404, detail="addon_not_found")
        registry.set_enabled(addon_id, body.enabled)
        return {"ok": True, "id": addon_id, "enabled": registry.is_enabled(addon_id)}

    @router.get("/addons/errors")
    def get_addon_errors():
        # Helpful when something fails to import but you still want the server up.
        return registry.errors

    @router.get("/system/addons/runtime")
    def list_standalone_runtimes(
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        items = [item.model_dump(mode="json") for item in runtime.list_standalone_addon_runtimes()]
        return {"ok": True, "items": items}

    @router.get("/system/addons/runtime/{addon_id}")
    def get_standalone_runtime(
        addon_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        item = runtime.get_standalone_addon_runtime(addon_id)
        return {"ok": True, "runtime": item.model_dump(mode="json")}

    return router

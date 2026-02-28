from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from ..addons.models import RegisteredAddon
from ..addons.registry import AddonRegistry
from .admin import require_admin_token


def build_admin_registry_router(registry: AddonRegistry) -> APIRouter:
    router = APIRouter()

    @router.get("/admin/addons/registry")
    def get_registered_addons(x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token)
        return [item.model_dump(mode="json") for item in registry.list_registered()]

    @router.post("/admin/addons/registry")
    def upsert_registered_addon(
        body: RegisteredAddon,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token)
        saved = registry.upsert_registered(body)
        return {"ok": True, "addon": saved.model_dump(mode="json")}

    @router.delete("/admin/addons/registry/{addon_id}")
    def delete_registered_addon(addon_id: str, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token)
        deleted = registry.delete_registered(addon_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="addon_not_found")
        return {"ok": True, "id": addon_id}

    return router

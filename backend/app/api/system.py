from __future__ import annotations

from fastapi import APIRouter
from ..addons.registry import AddonRegistry, list_addons

def build_system_router(registry: AddonRegistry) -> APIRouter:
    router = APIRouter()

    @router.get("/addons")
    def get_addons():
        return list_addons(registry)

    @router.get("/addons/errors")
    def get_addon_errors():
        # Helpful when something fails to import but you still want the server up.
        return registry.errors

    return router

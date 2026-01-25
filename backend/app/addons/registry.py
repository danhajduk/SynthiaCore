from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

from fastapi import FastAPI

from .discovery import discover_backend_addons
from .models import AddonMeta, BackendAddon

log = logging.getLogger("synthia.addons")

@dataclass
class AddonRegistry:
    addons: Dict[str, BackendAddon]
    errors: Dict[str, str]

def build_registry() -> AddonRegistry:
    discovered = discover_backend_addons()
    addons: Dict[str, BackendAddon] = {}
    errors: Dict[str, str] = {}

    for d in discovered:
        if d.addon is not None:
            addons[d.addon_id] = d.addon
            log.info("Loaded addon '%s' from %s", d.addon_id, d.module_path)
        else:
            errors[d.addon_id] = d.error or "Unknown error"
            log.error("Failed to load addon '%s' from %s\n%s", d.addon_id, d.module_path, errors[d.addon_id])

    return AddonRegistry(addons=addons, errors=errors)

def register_addons(app: FastAPI, registry: AddonRegistry) -> None:
    for addon_id, addon in registry.addons.items():
        prefix = f"/api/addons/{addon_id}"
        app.include_router(addon.router, prefix=prefix)

def list_addons(registry: AddonRegistry) -> List[AddonMeta]:
    return [a.meta for a in registry.addons.values()]

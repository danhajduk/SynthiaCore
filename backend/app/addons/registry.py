from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from fastapi import Depends, FastAPI, HTTPException

from .discovery import discover_backend_addons, repo_root
from .models import BackendAddon

log = logging.getLogger("synthia.addons")

@dataclass
class AddonRegistry:
    addons: Dict[str, BackendAddon]
    errors: Dict[str, str]
    enabled: Dict[str, bool]

    def is_enabled(self, addon_id: str) -> bool:
        return self.enabled.get(addon_id, True)

    def set_enabled(self, addon_id: str, enabled: bool) -> None:
        self.enabled[addon_id] = enabled
        _save_addon_state(self.enabled)
        log.info("Addon '%s' set to %s", addon_id, "enabled" if enabled else "disabled")


def _state_path() -> Path:
    return repo_root() / "data" / "addons_state.json"


def _load_addon_state() -> Dict[str, bool]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return {str(k): bool(v) for k, v in data.items()}
    except Exception as e:
        log.error("Failed to load addon state from %s: %s", path, e)
    return {}


def _save_addon_state(state: Dict[str, bool]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True))

def build_registry() -> AddonRegistry:
    log.info("Discovering backend addons")
    discovered = discover_backend_addons()
    addons: Dict[str, BackendAddon] = {}
    errors: Dict[str, str] = {}
    enabled = _load_addon_state()
    log.info("Discovered %d backend addons", len(discovered))

    for d in discovered:
        if d.addon is not None:
            addons[d.addon_id] = d.addon
            log.info("Loaded addon '%s' from %s", d.addon_id, d.module_path)
        else:
            errors[d.addon_id] = d.error or "Unknown error"
            log.error("Failed to load addon '%s' from %s\n%s", d.addon_id, d.module_path, errors[d.addon_id])

    changed = False
    for addon_id in addons.keys():
        if addon_id not in enabled:
            enabled[addon_id] = True
            changed = True
    if changed:
        _save_addon_state(enabled)

    return AddonRegistry(addons=addons, errors=errors, enabled=enabled)

def register_addons(app: FastAPI, registry: AddonRegistry) -> None:
    for addon_id, addon in registry.addons.items():
        prefix = f"/api/addons/{addon_id}"
        def _enabled_check(addon_id=addon_id):
            if not registry.is_enabled(addon_id):
                raise HTTPException(status_code=404, detail="addon_disabled")

        app.include_router(addon.router, prefix=prefix, dependencies=[Depends(_enabled_check)])

def list_addons(registry: AddonRegistry) -> List[dict]:
    out: List[dict] = []
    for addon_id, addon in registry.addons.items():
        meta = addon.meta.model_dump()
        meta["enabled"] = registry.is_enabled(addon_id)
        out.append(meta)
    return out

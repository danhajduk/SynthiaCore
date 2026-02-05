from __future__ import annotations

import importlib.util
import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import logging

from .models import BackendAddon, AddonMeta
log = logging.getLogger("synthia.addons")

@dataclass
class DiscoveredAddon:
    addon_id: str
    module_path: Path
    addon: BackendAddon | None
    error: str | None

def repo_root() -> Path:
    # backend/app/addons/discovery.py -> parents: addons(1), app(2), backend(3), repo(4)
    return Path(__file__).resolve().parents[4]

def addons_dir() -> Path:
    return repo_root() / "addons"

def discover_backend_addons() -> list[DiscoveredAddon]:
    log.info("Looking for backend addons in %s", addons_dir())
    base = addons_dir()
    if not base.exists():
        return []
    log.debug("Found %d addon folders in %s", len([p for p in base.iterdir() if p.is_dir()]), base)  

    results: list[DiscoveredAddon] = []
    for addon_folder in sorted([p for p in base.iterdir() if p.is_dir()]):
        log.debug("Processing addon folder: %s", addon_folder)
        addon_id = addon_folder.name
        manifest_path = addon_folder / "manifest.json"
        entry = addon_folder / "backend" / "addon.py"
        log.debug("Looking for manifest at %s and entrypoint at %s", manifest_path, entry)
        
        if not entry.exists():
            log.warning("Skipping addon '%s': missing backend/addon.py entrypoint", addon_id)
            continue

        try:
            if not manifest_path.exists():
                raise RuntimeError(f"Missing manifest.json for addon '{addon_id}'")

            manifest_data = json.loads(manifest_path.read_text())
            manifest_meta = AddonMeta.model_validate(manifest_data)

            if manifest_meta.id != addon_id:
                raise RuntimeError(
                    f"manifest.json id='{manifest_meta.id}' does not match folder name '{addon_id}'"
                )

            module_name = f"synthia_addons.{addon_id}"
            spec = importlib.util.spec_from_file_location(module_name, entry)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Could not create import spec for {entry}")

            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]

            raw = getattr(mod, "addon", None)
            if raw is None:
                raise RuntimeError("Backend addon entrypoint must export variable named `addon`")

            # Accept either BackendAddon instance or dict-like and validate via Pydantic
            addon = raw if isinstance(raw, BackendAddon) else BackendAddon.model_validate(raw)

            # Prefer manifest metadata as source of truth
            if addon.meta.id != manifest_meta.id:
                raise RuntimeError(
                    f"addon.meta.id='{addon.meta.id}' does not match manifest id '{manifest_meta.id}'"
                )
            addon = BackendAddon(meta=manifest_meta, router=addon.router)

            results.append(DiscoveredAddon(addon_id=addon_id, module_path=entry, addon=addon, error=None))

        except Exception as e:
            results.append(DiscoveredAddon(
                addon_id=addon_id,
                module_path=entry,
                addon=None,
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            ))

    return results

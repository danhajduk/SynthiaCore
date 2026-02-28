from __future__ import annotations

import importlib.util
import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import logging

from fastapi.routing import APIRoute

from .models import BackendAddon, AddonMeta
log = logging.getLogger("synthia.addons")

REQUIRED_CONTRACT_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("GET", "/api/addon/meta"),
    ("GET", "/api/addon/health"),
    ("GET", "/api/addon/capabilities"),
    ("GET", "/api/addon/config/effective"),
    ("POST", "/api/addon/config"),
)

@dataclass
class DiscoveredAddon:
    addon_id: str
    module_path: Path
    addon: BackendAddon | None
    error: str | None

def repo_root() -> Path:
    # backend/app/addons/discovery.py -> parents: addons(0), app(1), backend(2), repo(3)
    return Path(__file__).resolve().parents[3]

def addons_dir() -> Path:
    return repo_root() / "addons"


def _validate_backend_contract(addon: BackendAddon) -> list[str]:
    available: set[tuple[str, str]] = set()
    for route in addon.router.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        methods = route.methods or set()
        for method in methods:
            available.add((method.upper(), path))

    missing: list[str] = []
    for method, path in REQUIRED_CONTRACT_ENDPOINTS:
        if (method, path) not in available:
            missing.append(f"{method} {path}")
    return missing


def discover_backend_addons() -> list[DiscoveredAddon]:
    log.info("Looking for backend addons in %s", addons_dir())
    base = addons_dir()
    log.debug("Checking if addons directory exists at %s", base)
    if not base.exists():
        log.warning("Addons directory does not exist at %s", base)
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
            merged_meta = AddonMeta(
                id=manifest_meta.id,
                name=manifest_meta.name,
                version=manifest_meta.version,
                description=manifest_meta.description,
                show_sidebar=manifest_meta.show_sidebar,
                capabilities=addon.meta.capabilities,
                auth_modes=addon.meta.auth_modes,
                limits=addon.meta.limits,
                ui=addon.meta.ui,
            )
            addon = BackendAddon(meta=merged_meta, router=addon.router)
            missing = _validate_backend_contract(addon)
            if missing:
                raise RuntimeError(f"Addon contract endpoints missing: {', '.join(missing)}")

            results.append(DiscoveredAddon(addon_id=addon_id, module_path=entry, addon=addon, error=None))

        except Exception as e:
            results.append(DiscoveredAddon(
                addon_id=addon_id,
                module_path=entry,
                addon=None,
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            ))

    return results

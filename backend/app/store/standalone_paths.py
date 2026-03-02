from __future__ import annotations

import os
from pathlib import Path

from app.addons.discovery import repo_root

DEFAULT_ADDONS_DIR_NAME = "SynthiaAddons"


def _resolve_from_backend_dir(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    backend_dir = repo_root() / "backend"
    return (backend_dir / path).resolve()


def _validate_segment(name: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name}_empty")
    parts = Path(cleaned).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{name}_invalid")
    if len(parts) != 1:
        raise ValueError(f"{name}_invalid")
    return cleaned


def synthia_addons_dir() -> Path:
    raw = os.environ.get("SYNTHIA_ADDONS_DIR")
    if raw is None or not raw.strip():
        return (repo_root() / DEFAULT_ADDONS_DIR_NAME).resolve()
    return _resolve_from_backend_dir(raw.strip())


def services_root(*, create: bool = False) -> Path:
    path = synthia_addons_dir() / "services"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def service_addon_dir(addon_id: str, *, create: bool = False) -> Path:
    safe_addon_id = _validate_segment("addon_id", addon_id)
    path = services_root(create=create) / safe_addon_id
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def service_versions_dir(addon_id: str, *, create: bool = False) -> Path:
    path = service_addon_dir(addon_id, create=create) / "versions"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def service_version_dir(addon_id: str, version: str, *, create: bool = False) -> Path:
    safe_version = _validate_segment("version", version)
    path = service_versions_dir(addon_id, create=create) / safe_version
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def service_current_link(addon_id: str) -> Path:
    return service_addon_dir(addon_id, create=False) / "current"

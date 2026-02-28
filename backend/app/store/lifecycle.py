from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.addons.discovery import repo_root
from app.addons.registry import AddonRegistry
from .extract import extract_package, find_addon_dir, validate_addon_layout
from .models import ReleaseManifest


def addons_root() -> Path:
    return repo_root() / "addons"


def _env_int(name: str, default: int, min_value: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(min_value, int(raw))
    except ValueError:
        return default


def store_backup_retention() -> int:
    return _env_int("STORE_BACKUP_RETENTION", 3, min_value=0)


def store_staging_ttl_minutes() -> int:
    return _env_int("STORE_STAGING_TTL_MINUTES", 60, min_value=1)


def cleanup_store_workdirs(backup_retention: int, staging_ttl_minutes: int) -> dict[str, int]:
    base = addons_root()
    backup_root = base / ".store_backup"
    staging_root = base / ".store_staging"
    backup_root.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)

    backup_dirs = [p for p in backup_root.iterdir() if p.is_dir()]
    backup_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    backup_pruned = 0
    if backup_retention >= 0:
        for old in backup_dirs[backup_retention:]:
            shutil.rmtree(old, ignore_errors=True)
            backup_pruned += 1

    staging_pruned = 0
    cutoff = time.time() - (staging_ttl_minutes * 60)
    for entry in [p for p in staging_root.iterdir() if p.is_dir()]:
        if entry.stat().st_mtime < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            staging_pruned += 1

    return {"backup_pruned": backup_pruned, "staging_pruned": staging_pruned}


def installed_addons_with_versions(registry: AddonRegistry) -> dict[str, str]:
    out: dict[str, str] = {}
    for addon_id, addon in registry.addons.items():
        out[addon_id] = addon.meta.version

    root = addons_root()
    if root.exists():
        for entry in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            manifest_path = entry / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                addon_id = str(data.get("id", "")).strip() or entry.name
                version = str(data.get("version", "unknown")).strip() or "unknown"
                out[addon_id] = version
            except Exception:
                continue
    return out


@dataclass
class AtomicResult:
    addon_dir: Path
    backup_dir: Path | None
    # Internal-only metadata for future phases (catalog integrity + UI detail enrichments).
    # Not persisted in audit DB and not exposed directly to clients in Phase 1.
    installed_manifest: dict[str, Any]


def atomic_install_or_update(
    *,
    manifest: ReleaseManifest,
    package_path: Path,
    allow_replace: bool,
) -> AtomicResult:
    """
    Perform atomic addon install/update with rollback safety.

    Returns AtomicResult where installed_manifest is an internal-only payload
    kept for forward-compatible post-install validation paths.
    """
    root = addons_root()
    root.mkdir(parents=True, exist_ok=True)
    target_dir = root / manifest.id
    staging_root = root / ".store_staging"
    backup_root = root / ".store_backup"
    staging_root.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)

    if target_dir.exists() and not allow_replace:
        raise RuntimeError("addon_already_installed")

    work_dir = Path(tempfile.mkdtemp(prefix=f"{manifest.id}-", dir=str(staging_root)))
    extract_dir = work_dir / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)
    ready_dir = work_dir / "ready"

    backup_dir: Path | None = None
    manifest_data: dict[str, Any]

    try:
        extract_package(package_path, extract_dir)
        source_dir = find_addon_dir(extract_dir, manifest.id)
        manifest_data = validate_addon_layout(source_dir, manifest.id)
        shutil.copytree(source_dir, ready_dir)

        if target_dir.exists():
            backup_dir = backup_root / f"{manifest.id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            os.replace(target_dir, backup_dir)

        os.replace(ready_dir, target_dir)
        shutil.rmtree(work_dir, ignore_errors=True)
        return AtomicResult(addon_dir=target_dir, backup_dir=backup_dir, installed_manifest=manifest_data)
    except Exception:
        try:
            if target_dir.exists() and backup_dir is not None and backup_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
                os.replace(backup_dir, target_dir)
            elif (not target_dir.exists()) and backup_dir is not None and backup_dir.exists():
                os.replace(backup_dir, target_dir)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        raise


def atomic_uninstall(addon_id: str) -> None:
    target_dir = addons_root() / addon_id
    if not target_dir.exists():
        raise RuntimeError("addon_not_installed")

    staging_root = addons_root() / ".store_staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    trash_dir = Path(tempfile.mkdtemp(prefix=f"delete-{addon_id}-", dir=str(staging_root)))
    moved_dir = trash_dir / addon_id

    try:
        os.replace(target_dir, moved_dir)
        shutil.rmtree(moved_dir)
        shutil.rmtree(trash_dir, ignore_errors=True)
    except Exception:
        if moved_dir.exists() and not target_dir.exists():
            os.replace(moved_dir, target_dir)
        shutil.rmtree(trash_dir, ignore_errors=True)
        raise


class StoreInstallRequest(BaseModel):
    package_path: str | None = None
    manifest: ReleaseManifest | None = None
    public_key_pem: str | None = None
    source_id: str | None = None
    addon_id: str | None = None
    version: str | None = None
    enable: bool = True
    actor: str | None = None


class StoreUpdateRequest(BaseModel):
    package_path: str = Field(..., min_length=1)
    manifest: ReleaseManifest
    public_key_pem: str = Field(..., min_length=1)
    enable: bool = True
    actor: str | None = None


class StoreUninstallRequest(BaseModel):
    addon_id: str = Field(..., min_length=1)
    actor: str | None = None

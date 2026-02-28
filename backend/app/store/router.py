from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.addons.discovery import repo_root
from app.addons.registry import AddonRegistry
from app.api.admin import require_admin_token
from .catalog import CatalogQuery, StaticCatalogStore
from .models import ReleaseManifest
from .resolver import ResolverError, resolve_manifest_compatibility
from .signing import VerificationError, verify_release_artifact


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _addons_root() -> Path:
    return repo_root() / "addons"


def _safe_extract_zip(zip_path: Path, extract_dir: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise RuntimeError(f"unsafe_archive_path:{member.filename}")
            target = (extract_dir / member_path).resolve()
            if not str(target).startswith(str(extract_dir.resolve())):
                raise RuntimeError(f"unsafe_archive_target:{member.filename}")
        zf.extractall(extract_dir)


def _safe_extract_tar(tar_path: Path, extract_dir: Path) -> None:
    with tarfile.open(tar_path) as tf:
        for member in tf.getmembers():
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise RuntimeError(f"unsafe_archive_path:{member.name}")
            target = (extract_dir / member_path).resolve()
            if not str(target).startswith(str(extract_dir.resolve())):
                raise RuntimeError(f"unsafe_archive_target:{member.name}")
        tf.extractall(extract_dir)


def _extract_package(package_path: Path, extract_dir: Path) -> None:
    suffixes = [s.lower() for s in package_path.suffixes]
    if package_path.suffix.lower() == ".zip":
        _safe_extract_zip(package_path, extract_dir)
        return
    if suffixes[-2:] in [[".tar", ".gz"], [".tar", ".bz2"], [".tar", ".xz"]] or package_path.suffix.lower() == ".tar":
        _safe_extract_tar(package_path, extract_dir)
        return
    raise RuntimeError("unsupported_package_type")


def _find_addon_dir(extract_dir: Path, addon_id: str) -> Path:
    candidate = extract_dir / addon_id
    if candidate.is_dir():
        return candidate
    return extract_dir


def _validate_addon_layout(addon_dir: Path, addon_id: str) -> dict[str, Any]:
    manifest_path = addon_dir / "manifest.json"
    backend_entry = addon_dir / "backend" / "addon.py"
    if not manifest_path.exists():
        raise RuntimeError("missing_manifest_json")
    if not backend_entry.exists():
        raise RuntimeError("missing_backend_entrypoint")
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("invalid_manifest_json") from exc
    if str(manifest_data.get("id", "")).strip() != addon_id:
        raise RuntimeError("manifest_id_mismatch")
    return manifest_data


def _installed_addons_with_versions(registry: AddonRegistry) -> dict[str, str]:
    out: dict[str, str] = {}
    for addon_id, addon in registry.addons.items():
        out[addon_id] = addon.meta.version

    addons_root = _addons_root()
    if addons_root.exists():
        for entry in sorted(p for p in addons_root.iterdir() if p.is_dir() and not p.name.startswith(".")):
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


def _atomic_install_or_update(
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
    addons_root = _addons_root()
    addons_root.mkdir(parents=True, exist_ok=True)
    target_dir = addons_root / manifest.id
    staging_root = addons_root / ".store_staging"
    backup_root = addons_root / ".store_backup"
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
        _extract_package(package_path, extract_dir)
        source_dir = _find_addon_dir(extract_dir, manifest.id)
        manifest_data = _validate_addon_layout(source_dir, manifest.id)
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


def _atomic_uninstall(addon_id: str) -> None:
    target_dir = _addons_root() / addon_id
    if not target_dir.exists():
        raise RuntimeError("addon_not_installed")

    staging_root = _addons_root() / ".store_staging"
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
    package_path: str = Field(..., min_length=1)
    manifest: ReleaseManifest
    public_key_pem: str = Field(..., min_length=1)
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


class StoreAuditLogStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()
        self._init_db()

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS store_audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              timestamp TEXT NOT NULL,
              action TEXT NOT NULL,
              addon_id TEXT NOT NULL,
              version TEXT,
              status TEXT NOT NULL,
              message TEXT NOT NULL,
              actor TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_store_audit_ts ON store_audit_log(timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_store_audit_addon ON store_audit_log(addon_id)")
        self._conn.commit()

    async def record(
        self,
        *,
        action: str,
        addon_id: str,
        version: str | None,
        status: str,
        message: str,
        actor: str | None,
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(self._record_sync, action, addon_id, version, status, message, actor)

    def _record_sync(
        self,
        action: str,
        addon_id: str,
        version: str | None,
        status: str,
        message: str,
        actor: str | None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO store_audit_log (timestamp, action, addon_id, version, status, message, actor)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (_utcnow_iso(), action, addon_id, version, status, message, actor),
        )
        self._conn.commit()


def build_store_router(registry: AddonRegistry, audit_store: StoreAuditLogStore) -> APIRouter:
    router = APIRouter()
    catalog_store = StaticCatalogStore.from_default_path()

    @router.get("/catalog")
    async def get_catalog(
        q: str | None = Query(default=None),
        category: str | None = Query(default=None),
        featured: bool | None = Query(default=None),
        sort: str = Query(default="recent"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ):
        return catalog_store.query(
            CatalogQuery(
                q=q,
                category=category,
                featured=featured,
                sort=sort,
                page=page,
                page_size=page_size,
            )
        )

    @router.post("/install")
    async def install_addon(
        body: StoreInstallRequest,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token)
        package_path = Path(body.package_path)
        if not package_path.exists() or not package_path.is_file():
            raise HTTPException(status_code=400, detail="package_path_not_found")

        actor = body.actor or "admin_token"
        try:
            artifact_bytes = package_path.read_bytes()
            verify_release_artifact(body.manifest, artifact_bytes, body.public_key_pem)

            resolve_manifest_compatibility(
                body.manifest,
                core_version=os.getenv("SYNTHIA_CORE_VERSION", "0.1.0"),
                installed_addons=_installed_addons_with_versions(registry),
            )

            result = _atomic_install_or_update(
                manifest=body.manifest,
                package_path=package_path,
                allow_replace=False,
            )

            if body.enable:
                registry.set_enabled(body.manifest.id, True)

            await audit_store.record(
                action="install",
                addon_id=body.manifest.id,
                version=body.manifest.version,
                status="success",
                message="install_completed",
                actor=actor,
            )
            return {
                "ok": True,
                "addon_id": body.manifest.id,
                "version": body.manifest.version,
                "installed_path": str(result.addon_dir),
                "enabled": registry.is_enabled(body.manifest.id),
                "registry_loaded": body.manifest.id in registry.addons,
                # TODO(phase3): report true hot-reload runtime status once dynamic module reload is supported.
                "hot_loaded": False,
            }
        except VerificationError as exc:
            await audit_store.record(
                action="install",
                addon_id=body.manifest.id,
                version=body.manifest.version,
                status="failed",
                message=exc.code,
                actor=actor,
            )
            raise HTTPException(status_code=400, detail=exc.to_dict())
        except ResolverError as exc:
            await audit_store.record(
                action="install",
                addon_id=body.manifest.id,
                version=body.manifest.version,
                status="failed",
                message=exc.code,
                actor=actor,
            )
            raise HTTPException(status_code=409, detail=exc.to_dict())
        except Exception as exc:
            await audit_store.record(
                action="install",
                addon_id=body.manifest.id,
                version=body.manifest.version,
                status="failed",
                message=type(exc).__name__,
                actor=actor,
            )
            detail = str(exc) or type(exc).__name__
            if detail == "addon_already_installed":
                raise HTTPException(status_code=409, detail=detail)
            raise HTTPException(status_code=400, detail=detail)

    @router.post("/update")
    async def update_addon(
        body: StoreUpdateRequest,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token)
        package_path = Path(body.package_path)
        if not package_path.exists() or not package_path.is_file():
            raise HTTPException(status_code=400, detail="package_path_not_found")

        actor = body.actor or "admin_token"
        try:
            artifact_bytes = package_path.read_bytes()
            verify_release_artifact(body.manifest, artifact_bytes, body.public_key_pem)

            resolve_manifest_compatibility(
                body.manifest,
                core_version=os.getenv("SYNTHIA_CORE_VERSION", "0.1.0"),
                installed_addons=_installed_addons_with_versions(registry),
            )

            result = _atomic_install_or_update(
                manifest=body.manifest,
                package_path=package_path,
                allow_replace=True,
            )

            if body.enable:
                registry.set_enabled(body.manifest.id, True)

            await audit_store.record(
                action="update",
                addon_id=body.manifest.id,
                version=body.manifest.version,
                status="success",
                message="update_completed",
                actor=actor,
            )
            return {
                "ok": True,
                "addon_id": body.manifest.id,
                "version": body.manifest.version,
                "installed_path": str(result.addon_dir),
                "enabled": registry.is_enabled(body.manifest.id),
                "registry_loaded": body.manifest.id in registry.addons,
                # TODO(phase3): report true hot-reload runtime status once dynamic module reload is supported.
                "hot_loaded": False,
            }
        except VerificationError as exc:
            await audit_store.record(
                action="update",
                addon_id=body.manifest.id,
                version=body.manifest.version,
                status="failed",
                message=exc.code,
                actor=actor,
            )
            raise HTTPException(status_code=400, detail=exc.to_dict())
        except ResolverError as exc:
            await audit_store.record(
                action="update",
                addon_id=body.manifest.id,
                version=body.manifest.version,
                status="failed",
                message=exc.code,
                actor=actor,
            )
            raise HTTPException(status_code=409, detail=exc.to_dict())
        except Exception as exc:
            await audit_store.record(
                action="update",
                addon_id=body.manifest.id,
                version=body.manifest.version,
                status="failed",
                message=type(exc).__name__,
                actor=actor,
            )
            detail = str(exc) or type(exc).__name__
            raise HTTPException(status_code=400, detail=detail)

    @router.post("/uninstall")
    async def uninstall_addon(
        body: StoreUninstallRequest,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token)
        actor = body.actor or "admin_token"
        addon_id = body.addon_id.strip()

        try:
            manifest_path = _addons_root() / addon_id / "manifest.json"
            version = None
            if manifest_path.exists():
                try:
                    version = str(json.loads(manifest_path.read_text(encoding="utf-8")).get("version", "unknown"))
                except Exception:
                    version = None

            _atomic_uninstall(addon_id)
            registry.set_enabled(addon_id, False)
            await audit_store.record(
                action="uninstall",
                addon_id=addon_id,
                version=version,
                status="success",
                message="uninstall_completed",
                actor=actor,
            )
            return {"ok": True, "addon_id": addon_id, "enabled": registry.is_enabled(addon_id)}
        except Exception as exc:
            await audit_store.record(
                action="uninstall",
                addon_id=addon_id,
                version=None,
                status="failed",
                message=type(exc).__name__,
                actor=actor,
            )
            detail = str(exc) or type(exc).__name__
            if detail == "addon_not_installed":
                raise HTTPException(status_code=404, detail=detail)
            raise HTTPException(status_code=400, detail=detail)

    @router.get("/status/{addon_id}")
    async def addon_store_status(addon_id: str):
        target = _addons_root() / addon_id
        manifest_path = target / "manifest.json"
        version = None
        if manifest_path.exists():
            try:
                version = str(json.loads(manifest_path.read_text(encoding="utf-8")).get("version", "unknown"))
            except Exception:
                version = None

        return {
            "ok": True,
            "addon_id": addon_id,
            "installed": target.exists(),
            "loaded": addon_id in registry.addons,
            "enabled": registry.is_enabled(addon_id),
            "version": version or (registry.addons[addon_id].meta.version if addon_id in registry.addons else None),
        }

    return router

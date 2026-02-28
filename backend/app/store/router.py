from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query

from app.addons.registry import AddonRegistry
from app.api.admin import require_admin_token
from .audit import StoreAuditLogStore
from .catalog import CatalogQuery, StaticCatalogStore
from . import lifecycle as lifecycle_mod
from .lifecycle import (
    AtomicResult,
    StoreInstallRequest,
    StoreUpdateRequest,
    StoreUninstallRequest,
    addons_root,
    atomic_install_or_update,
    atomic_uninstall,
    cleanup_store_workdirs,
    installed_addons_with_versions,
    store_backup_retention,
    store_staging_ttl_minutes,
)
from .resolver import ResolverError, resolve_manifest_compatibility
from .signing import VerificationError, verify_release_artifact
from .sources import StoreSource, StoreSourcesStore

# Backward-compatible wrappers kept for tests and gradual refactor migration.
def _addons_root():
    return addons_root()


def _atomic_install_or_update(*, manifest, package_path, allow_replace):
    orig = lifecycle_mod.addons_root
    lifecycle_mod.addons_root = _addons_root
    try:
        return atomic_install_or_update(manifest=manifest, package_path=package_path, allow_replace=allow_replace)
    finally:
        lifecycle_mod.addons_root = orig


def _cleanup_store_workdirs(backup_retention: int, staging_ttl_minutes: int):
    orig = lifecycle_mod.addons_root
    lifecycle_mod.addons_root = _addons_root
    try:
        return cleanup_store_workdirs(backup_retention=backup_retention, staging_ttl_minutes=staging_ttl_minutes)
    finally:
        lifecycle_mod.addons_root = orig


def build_store_router(
    registry: AddonRegistry,
    audit_store: StoreAuditLogStore,
    sources_store: StoreSourcesStore | None = None,
) -> APIRouter:
    router = APIRouter()
    catalog_store = StaticCatalogStore.from_default_path()
    sources = sources_store

    @router.get("/catalog")
    async def get_catalog(
        q: str | None = Query(default=None),
        category: str | None = Query(default=None),
        featured: bool | None = Query(default=None),
        sort: str = Query(default="recent"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ):
        payload = catalog_store.query(
            CatalogQuery(
                q=q,
                category=category,
                featured=featured,
                sort=sort,
                page=page,
                page_size=page_size,
            )
        )
        status = payload.get("catalog_status", {})
        if status.get("status") == "error":
            await audit_store.record(
                action="catalog_query",
                addon_id="__catalog__",
                version=None,
                status="failed",
                message=str(status.get("message") or "catalog_error"),
                actor="system",
            )
        return payload

    @router.get("/sources")
    async def list_store_sources():
        if sources is None:
            return {"ok": True, "items": []}
        items = await sources.list_sources()
        return {"ok": True, "items": [x.model_dump(mode="json") for x in items]}

    @router.post("/sources")
    async def upsert_store_source(
        body: StoreSource,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token)
        if sources is None:
            raise HTTPException(status_code=500, detail="sources_store_not_configured")
        try:
            saved = await sources.upsert_source(body)
            return {"ok": True, "source": saved.model_dump(mode="json")}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc) or type(exc).__name__)

    @router.delete("/sources/{source_id}")
    async def delete_store_source(source_id: str, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token)
        if sources is None:
            raise HTTPException(status_code=500, detail="sources_store_not_configured")
        try:
            deleted = await sources.delete_source(source_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="source_not_found")
            return {"ok": True, "id": source_id}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc) or type(exc).__name__)

    @router.post("/sources/{source_id}/refresh")
    async def refresh_store_source(source_id: str, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token)
        if sources is None:
            raise HTTPException(status_code=500, detail="sources_store_not_configured")
        try:
            saved = await sources.mark_refresh(source_id)
            return {"ok": True, "source": saved.model_dump(mode="json")}
        except Exception as exc:
            msg = str(exc) or type(exc).__name__
            if msg == "source_not_found":
                raise HTTPException(status_code=404, detail=msg)
            raise HTTPException(status_code=400, detail=msg)

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
            cleanup = _cleanup_store_workdirs(
                backup_retention=store_backup_retention(),
                staging_ttl_minutes=store_staging_ttl_minutes(),
            )
            if cleanup["backup_pruned"] or cleanup["staging_pruned"]:
                await audit_store.record(
                    action="maintenance_cleanup",
                    addon_id=body.manifest.id,
                    version=None,
                    status="success",
                    message=f"backup_pruned={cleanup['backup_pruned']};staging_pruned={cleanup['staging_pruned']}",
                    actor=actor,
                )

            artifact_bytes = package_path.read_bytes()
            verify_release_artifact(body.manifest, artifact_bytes, body.public_key_pem)

            resolve_manifest_compatibility(
                body.manifest,
                core_version=os.getenv("SYNTHIA_CORE_VERSION", "0.1.0"),
                installed_addons=installed_addons_with_versions(registry),
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
            cleanup = _cleanup_store_workdirs(
                backup_retention=store_backup_retention(),
                staging_ttl_minutes=store_staging_ttl_minutes(),
            )
            if cleanup["backup_pruned"] or cleanup["staging_pruned"]:
                await audit_store.record(
                    action="maintenance_cleanup",
                    addon_id=body.manifest.id,
                    version=None,
                    status="success",
                    message=f"backup_pruned={cleanup['backup_pruned']};staging_pruned={cleanup['staging_pruned']}",
                    actor=actor,
                )

            artifact_bytes = package_path.read_bytes()
            verify_release_artifact(body.manifest, artifact_bytes, body.public_key_pem)

            resolve_manifest_compatibility(
                body.manifest,
                core_version=os.getenv("SYNTHIA_CORE_VERSION", "0.1.0"),
                installed_addons=installed_addons_with_versions(registry),
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

            atomic_uninstall(addon_id)
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

    @router.get("/admin/audit")
    async def store_audit_list(
        addon_id: str | None = Query(default=None),
        action: str | None = Query(default=None),
        status: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token)
        return await audit_store.list_rows(
            addon_id=addon_id,
            action=action,
            status=status,
            page=page,
            page_size=page_size,
        )

    return router

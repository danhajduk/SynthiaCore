from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Query, Request

from app.addons.registry import AddonRegistry
from app.api.admin import require_admin_token
from .audit import StoreAuditLogStore
from .catalog import CatalogCacheClient, CatalogQuery, StaticCatalogStore
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
from .models import ReleaseManifest
from .resolver import ResolverError, resolve_manifest_compatibility
from .signing import VerificationError, verify_detached_artifact_signature, verify_release_artifact
from .sources import StoreSource, StoreSourcesStore

log = logging.getLogger("synthia.store")

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


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_install_state_path() -> Path:
    return Path(os.getenv("STORE_INSTALL_STATE_PATH", os.path.join("var", "store_install_state.json")))


def _load_install_state() -> dict[str, Any]:
    path = _store_install_state_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        return {}
    return {}


def _save_install_state(payload: dict[str, Any]) -> None:
    path = _store_install_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _set_install_state(addon_id: str, data: dict[str, Any]) -> None:
    state = _load_install_state()
    state[addon_id] = data
    _save_install_state(state)


def _update_install_state(addon_id: str, data: dict[str, Any]) -> None:
    state = _load_install_state()
    current = state.get(addon_id)
    payload: dict[str, Any] = dict(current) if isinstance(current, dict) else {}
    payload.update(data)
    state[addon_id] = payload
    _save_install_state(state)


def _clear_install_state(addon_id: str) -> None:
    state = _load_install_state()
    if addon_id in state:
        del state[addon_id]
        _save_install_state(state)


def _get_install_state(addon_id: str) -> dict[str, Any] | None:
    state = _load_install_state()
    value = state.get(addon_id)
    if isinstance(value, dict):
        return value
    return None


def _resolved_base_url_for_source(
    cache_catalog: CatalogCacheClient,
    source_id: str | None,
    fallback: str | None = None,
) -> str | None:
    if not source_id:
        return fallback
    loader = getattr(cache_catalog, "load_source_metadata", None)
    if not callable(loader):
        return fallback
    try:
        payload = loader(source_id)
    except Exception:
        return fallback
    if not isinstance(payload, dict):
        return fallback
    resolved = str(payload.get("resolved_base_url") or "").strip()
    return resolved or fallback


def _installed_summary_map() -> dict[str, dict[str, Any]]:
    state = _load_install_state()
    out: dict[str, dict[str, Any]] = {}
    for addon_id, raw in state.items():
        if not isinstance(raw, dict):
            continue
        version = raw.get("installed_version")
        installed_at = raw.get("installed_at")
        if version is None and installed_at is None:
            continue
        out[str(addon_id)] = {
            "version": version,
            "installed_at": installed_at,
        }
    return out


def _hex_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _configured_core_version() -> str:
    return os.getenv("SYNTHIA_CORE_VERSION", "0.1.0")


def _extract_catalog_items(index_payload: Any) -> list[dict[str, Any]]:
    if isinstance(index_payload, list):
        return [x for x in index_payload if isinstance(x, dict)]
    if isinstance(index_payload, dict):
        if isinstance(index_payload.get("items"), list):
            return [x for x in index_payload.get("items", []) if isinstance(x, dict)]
        if isinstance(index_payload.get("addons"), list):
            return [x for x in index_payload.get("addons", []) if isinstance(x, dict)]
    return []


def _release_artifact_payload(release_item: dict[str, Any]) -> dict[str, Any]:
    artifact = release_item.get("artifact")
    if isinstance(artifact, dict):
        return artifact
    return {}


def _release_artifact_url(release_item: dict[str, Any]) -> str:
    artifact = _release_artifact_payload(release_item)
    return str(
        release_item.get("artifact_url")
        or release_item.get("url")
        or release_item.get("download_url")
        or artifact.get("url")
        or artifact.get("artifact_url")
        or artifact.get("download_url")
        or ""
    ).strip()


def _artifact_temp_filename(artifact_url: str | None) -> str:
    path = urlparse(str(artifact_url or "")).path.lower()
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".zip", ".tar"):
        if path.endswith(suffix):
            return f"artifact{suffix}"
    return "artifact.bin"


def _release_signature_b64(release_item: dict[str, Any]) -> str:
    artifact = _release_artifact_payload(release_item)
    release_signature = release_item.get("signature")
    if isinstance(release_signature, dict):
        value = str(
            release_signature.get("value")
            or release_signature.get("signature")
            or release_signature.get("sig")
            or ""
        ).strip()
        if value:
            return value
    artifact_signature = artifact.get("signature")
    if isinstance(artifact_signature, dict):
        value = str(
            artifact_signature.get("value")
            or artifact_signature.get("signature")
            or artifact_signature.get("sig")
            or ""
        ).strip()
        if value:
            return value
    return str(
        release_item.get("release_sig")
        or release_item.get("signature")
        or artifact.get("release_sig")
        or artifact.get("signature")
        or ""
    ).strip()


def _release_signature_type(release_item: dict[str, Any]) -> str:
    artifact = _release_artifact_payload(release_item)
    release_signature = release_item.get("signature")
    if isinstance(release_signature, dict):
        sig_type = str(
            release_signature.get("type")
            or release_signature.get("signature_type")
            or ""
        ).strip().lower()
        if sig_type:
            return sig_type
    artifact_signature = artifact.get("signature")
    if isinstance(artifact_signature, dict):
        sig_type = str(
            artifact_signature.get("type")
            or artifact_signature.get("signature_type")
            or ""
        ).strip().lower()
        if sig_type:
            return sig_type
    return str(
        release_item.get("signature_type")
        or release_item.get("release_sig_type")
        or artifact.get("signature_type")
        or "rsa-sha256"
    ).strip().lower()


def _release_checksum(release_item: dict[str, Any]) -> str:
    artifact = _release_artifact_payload(release_item)
    return str(
        release_item.get("sha256")
        or release_item.get("checksum")
        or artifact.get("sha256")
        or artifact.get("checksum")
        or ""
    ).strip()


def _normalize_package_profile(value: Any) -> str:
    normalized = str(value or "embedded_addon").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "embedded": "embedded_addon",
        "addon": "embedded_addon",
        "standalone": "standalone_service",
        "service": "standalone_service",
    }
    return aliases.get(normalized, normalized)


def _release_package_profile(addon_item: dict[str, Any], release_item: dict[str, Any]) -> str:
    return _normalize_package_profile(
        release_item.get("package_profile")
        or addon_item.get("package_profile")
        or release_item.get("profile")
        or addon_item.get("profile")
        or "embedded_addon"
    )


def _normalize_sha256(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    if not text:
        return ""
    for prefix in ("sha256:", "sha256=", "sha256-"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    if len(text) == 64 and all(ch in "0123456789abcdef" for ch in text):
        return text
    return ""


def _release_checksum_candidates(release_item: dict[str, Any], manifest_checksum: str | None = None) -> list[str]:
    artifact = _release_artifact_payload(release_item)
    raw_candidates: list[str | None] = [
        _release_checksum(release_item),
        str(release_item.get("digest") or "").strip(),
        str(release_item.get("integrity") or "").strip(),
        str(artifact.get("digest") or "").strip(),
        str(artifact.get("integrity") or "").strip(),
        manifest_checksum,
    ]
    checksums_payload = artifact.get("checksums")
    if isinstance(checksums_payload, dict):
        raw_candidates.append(str(checksums_payload.get("sha256") or "").strip())

    normalized: list[str] = []
    for raw in raw_candidates:
        checksum = _normalize_sha256(raw)
        if checksum and checksum not in normalized:
            normalized.append(checksum)
    return normalized


def _parse_semver_key(value: str) -> tuple[int, int, int, str]:
    try:
        base = value.split("-", 1)[0]
        major, minor, patch = base.split(".", 2)
        return (int(major), int(minor), int(patch), value)
    except Exception:
        return (-1, -1, -1, value)


def _build_release_manifest(addon_id: str, addon_item: dict[str, Any], release_item: dict[str, Any]) -> ReleaseManifest:
    compatibility_raw = release_item.get("compatibility") or addon_item.get("compatibility") or {}
    compat = {
        "core_min_version": compatibility_raw.get("core_min_version")
        or compatibility_raw.get("core_min")
        or release_item.get("core_min_version")
        or release_item.get("core_min")
        or addon_item.get("core_min_version")
        or addon_item.get("core_min")
        or "0.1.0",
        "core_max_version": compatibility_raw.get("core_max_version")
        or compatibility_raw.get("core_max")
        or release_item.get("core_max_version")
        or release_item.get("core_max")
        or addon_item.get("core_max_version"),
        "dependencies": compatibility_raw.get("dependencies")
        or release_item.get("dependencies")
        or addon_item.get("dependencies")
        or [],
        "conflicts": compatibility_raw.get("conflicts")
        or release_item.get("conflicts")
        or addon_item.get("conflicts")
        or [],
    }
    publisher_key_id = str(
        release_item.get("publisher_key_id")
        or addon_item.get("publisher_key_id")
        or release_item.get("key_id")
        or addon_item.get("key_id")
        or ""
    ).strip()
    publisher_id_from_key = publisher_key_id.split("#", 1)[0].strip() if "#" in publisher_key_id else ""
    publisher_id = str(
        release_item.get("publisher_id")
        or addon_item.get("publisher_id")
        or release_item.get("publisher")
        or addon_item.get("publisher")
        or publisher_id_from_key
        or ""
    ).strip()
    signature_b64 = _release_signature_b64(release_item)
    checksum = _release_checksum(release_item)
    package_profile = _release_package_profile(addon_item, release_item)

    manifest_payload = release_item.get("manifest")
    if isinstance(manifest_payload, dict):
        data = dict(manifest_payload)
        data.setdefault("id", addon_id)
        data.setdefault("name", str(addon_item.get("name") or addon_id))
        data.setdefault("version", str(release_item.get("version") or addon_item.get("version") or "").strip())
        data.setdefault("publisher_id", publisher_id)
        data.setdefault("checksum", checksum)
        data.setdefault("package_profile", package_profile)
        data.setdefault("signature", {"publisher_id": publisher_id, "signature": signature_b64})
        data.setdefault("compatibility", compat)
        data.setdefault("permissions", addon_item.get("permissions") or release_item.get("permissions") or [])
        return ReleaseManifest.model_validate(data)

    return ReleaseManifest.model_validate(
        {
            "id": addon_id,
            "name": str(addon_item.get("name") or addon_id),
            "version": str(release_item.get("version") or addon_item.get("version") or "").strip(),
            "core_min_version": compat["core_min_version"],
            "core_max_version": compat["core_max_version"],
            "dependencies": compat["dependencies"],
            "conflicts": compat["conflicts"],
            "checksum": checksum,
            "publisher_id": publisher_id,
            "package_profile": package_profile,
            "permissions": addon_item.get("permissions") or release_item.get("permissions") or [],
            "signature": {"publisher_id": publisher_id, "signature": signature_b64},
            "compatibility": compat,
        }
    )


def _publisher_key_from_payload(
    publishers_payload: Any,
    *,
    publisher_id: str,
    publisher_key_id: str,
) -> tuple[str, str] | None:
    if not isinstance(publishers_payload, dict):
        return None
    publishers = publishers_payload.get("publishers")
    if not isinstance(publishers, list):
        return None
    for pub in publishers:
        if not isinstance(pub, dict):
            continue
        pub_id = str(pub.get("id") or pub.get("publisher_id") or "").strip()
        if pub_id != publisher_id:
            continue
        pub_enabled = pub.get("enabled")
        if pub_enabled is False:
            continue
        if pub_enabled is None and str(pub.get("status") or "enabled").strip().lower() != "enabled":
            continue
        keys = pub.get("keys")
        if isinstance(keys, list):
            for item in keys:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or item.get("key_id") or "").strip()
                if item_id != publisher_key_id:
                    continue
                item_enabled = item.get("enabled")
                if item_enabled is False:
                    continue
                if item_enabled is None and str(item.get("status") or "enabled").strip().lower() != "enabled":
                    continue
                pem = item.get("public_key_pem") or item.get("pem")
                if isinstance(pem, str) and pem.strip():
                    sig_type = str(item.get("signature_type") or item.get("type") or "rsa-sha256").strip().lower()
                    return pem, sig_type
        # Backward-compat shape: publisher carries a single key directly.
        if str(pub.get("key_id", "")).strip() == publisher_key_id:
            pem = pub.get("public_key_pem")
            if isinstance(pem, str) and pem.strip():
                sig_type = str(pub.get("signature_type") or pub.get("type") or "rsa-sha256").strip().lower()
                return pem, sig_type
    return None


def _resolve_catalog_release(
    index_payload: Any,
    addon_id: str,
    version: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    addon_item: dict[str, Any] | None = None
    for item in _extract_catalog_items(index_payload):
        item_id = str(item.get("id") or item.get("addon_id") or "").strip()
        if not item_id:
            manifest = item.get("manifest")
            if isinstance(manifest, dict):
                item_id = str(manifest.get("id") or "").strip()
        if item_id == addon_id:
            addon_item = item
            break
    if addon_item is None:
        raise RuntimeError("catalog_addon_not_found")

    def _channel_release_entries(raw_channel: Any) -> list[dict[str, Any]]:
        if isinstance(raw_channel, list):
            return [dict(item) for item in raw_channel if isinstance(item, dict)]
        if isinstance(raw_channel, dict):
            nested = raw_channel.get("releases")
            if isinstance(nested, list):
                return [dict(item) for item in nested if isinstance(item, dict)]
            if "version" in raw_channel:
                return [dict(raw_channel)]
        return []

    release_items: list[dict[str, Any]] = []
    channels = addon_item.get("channels")
    if isinstance(channels, dict):
        preferred_order = ["stable", "beta", "nightly"]
        remaining = [name for name in channels.keys() if str(name) not in preferred_order]
        channel_names = preferred_order + sorted(str(name) for name in remaining)
        for channel_name in channel_names:
            entries = _channel_release_entries(channels.get(channel_name))
            channel_release_items: list[dict[str, Any]] = []
            for item in entries:
                row = dict(item)
                row.setdefault("channel", channel_name)
                channel_release_items.append(row)
            channel_release_items.sort(key=lambda r: _parse_semver_key(str(r.get("version", ""))), reverse=True)
            release_items.extend(channel_release_items)

    releases = addon_item.get("releases")
    if isinstance(releases, list) and not release_items:
        release_items.extend([x for x in releases if isinstance(x, dict)])

    if not release_items:
        raise RuntimeError("catalog_releases_missing")

    if version and version.strip():
        for rel in release_items:
            if str(rel.get("version", "")).strip() == version.strip():
                return addon_item, [rel]
        raise RuntimeError("catalog_release_version_not_found")

    if not isinstance(channels, dict):
        release_items.sort(key=lambda r: _parse_semver_key(str(r.get("version", ""))), reverse=True)
    return addon_item, release_items


def build_store_router(
    registry: AddonRegistry,
    audit_store: StoreAuditLogStore,
    sources_store: StoreSourcesStore | None = None,
    catalog_client: CatalogCacheClient | None = None,
) -> APIRouter:
    router = APIRouter()
    static_catalog = StaticCatalogStore.from_default_path()
    cache_catalog = catalog_client or CatalogCacheClient.from_default_path()
    sources = sources_store

    @router.get("/catalog")
    async def get_catalog(
        source_id: str | None = Query(default=None),
        q: str | None = Query(default=None),
        category: str | None = Query(default=None),
        featured: bool | None = Query(default=None),
        sort: str = Query(default="recent"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ):
        req = CatalogQuery(
            q=q,
            category=category,
            featured=featured,
            sort=sort,
            page=page,
            page_size=page_size,
        )
        if sources is None:
            payload = static_catalog.query(req)
        else:
            source_items = await sources.list_sources()
            selected = cache_catalog.select_source(source_items, source_id)
            if selected is None:
                payload = {
                    "ok": True,
                    "items": [],
                    "page": page,
                    "page_size": page_size,
                    "total": 0,
                    "has_next": False,
                    "sort": sort,
                    "filters": {"q": q, "category": category, "featured": featured},
                    "categories": [],
                    "catalog_status": {
                        "status": "error",
                        "source_id": source_id,
                        "last_success_at": None,
                        "last_error_at": None,
                        "last_error_message": "store_source_not_found_or_disabled",
                    },
                }
            else:
                payload = cache_catalog.query_cached(selected.id, req)
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
        payload["installed"] = _installed_summary_map()
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
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        if sources is None:
            raise HTTPException(status_code=500, detail="sources_store_not_configured")
        try:
            saved = await sources.upsert_source(body)
            return {"ok": True, "source": saved.model_dump(mode="json")}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc) or type(exc).__name__)

    @router.delete("/sources/{source_id}")
    async def delete_store_source(source_id: str, request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
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
    async def refresh_store_source(source_id: str, request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        if sources is None:
            raise HTTPException(status_code=500, detail="sources_store_not_configured")
        try:
            saved = await sources.mark_refresh(source_id)
            refresh = cache_catalog.refresh_source(saved)
            return {"ok": True, "source": saved.model_dump(mode="json"), "refresh": refresh}
        except Exception as exc:
            msg = str(exc) or type(exc).__name__
            if msg == "source_not_found":
                raise HTTPException(status_code=404, detail=msg)
            raise HTTPException(status_code=400, detail=msg)

    @router.post("/install")
    async def install_addon(
        body: StoreInstallRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        actor = body.actor or "admin_token"
        local_install = bool(body.package_path and body.manifest and body.public_key_pem)
        catalog_install = bool(body.addon_id)
        if local_install and catalog_install:
            raise HTTPException(status_code=400, detail="install_mode_conflict")
        if not local_install and not catalog_install:
            raise HTTPException(status_code=400, detail="install_mode_missing")
        temp_install_dir: Path | None = None
        target_addon_id = (
            body.addon_id.strip()
            if body.addon_id and body.addon_id.strip()
            else (body.manifest.id if body.manifest is not None else None)
        )
        debug_source_id: str | None = None
        debug_resolved_base_url: str | None = None
        debug_artifact_url: str | None = None
        debug_expected_sha256: list[str] | None = None
        debug_actual_sha256: str | None = None
        debug_publisher_key_id: str | None = None
        debug_signature_type: str | None = None
        debug_package_profile: str | None = None

        def _persist_last_install_error(
            *,
            error_code: str | None,
            source_id: str | None = None,
            resolved_base_url: str | None = None,
            artifact_url: str | None = None,
            expected_sha256: list[str] | None = None,
            actual_sha256: str | None = None,
            publisher_key_id: str | None = None,
            signature_type: str | None = None,
        ) -> None:
            if not catalog_install or not target_addon_id:
                return
            sid = source_id or debug_source_id
            resolved = _resolved_base_url_for_source(
                cache_catalog,
                sid,
                resolved_base_url or debug_resolved_base_url,
            )
            payload = {
                "error": error_code or "install_failed",
                "source_id": sid,
                "resolved_base_url": resolved,
                "artifact_url": artifact_url or debug_artifact_url,
                "expected_sha256": expected_sha256 if expected_sha256 is not None else debug_expected_sha256,
                "actual_sha256": actual_sha256 or debug_actual_sha256,
                "publisher_key_id": publisher_key_id or debug_publisher_key_id,
                "signature_type": signature_type or debug_signature_type,
                "occurred_at": _utcnow_iso(),
            }
            _update_install_state(target_addon_id, {"last_install_error": payload})

        try:
            cleanup = _cleanup_store_workdirs(
                backup_retention=store_backup_retention(),
                staging_ttl_minutes=store_staging_ttl_minutes(),
            )
            if cleanup["backup_pruned"] or cleanup["staging_pruned"]:
                await audit_store.record(
                    action="maintenance_cleanup",
                    addon_id=(body.manifest.id if body.manifest is not None else (body.addon_id or "__unknown__")),
                    version=None,
                    status="success",
                    message=f"backup_pruned={cleanup['backup_pruned']};staging_pruned={cleanup['staging_pruned']}",
                    actor=actor,
                )
            source_id = "local"
            source_release_url: str | None = None
            expected_sha256: str | None = None
            package_path: Path
            manifest: ReleaseManifest
            public_key_pem: str
            release_signature_b64: str | None = None
            release_signature_type: str = "rsa-sha256"

            if local_install:
                package_path = Path(str(body.package_path))
                if not package_path.exists() or not package_path.is_file():
                    raise HTTPException(status_code=400, detail="package_path_not_found")
                manifest = body.manifest  # type: ignore[assignment]
                public_key_pem = str(body.public_key_pem)
                artifact_bytes = package_path.read_bytes()
                expected_sha256 = manifest.checksum
                debug_package_profile = manifest.package_profile
                debug_source_id = source_id
            else:
                if sources is None:
                    raise HTTPException(status_code=500, detail="sources_store_not_configured")
                if not body.addon_id or not body.addon_id.strip():
                    raise HTTPException(status_code=400, detail="catalog_addon_id_missing")
                requested_source_id = body.source_id.strip() if body.source_id else None
                source_items = await sources.list_sources()
                selected = cache_catalog.select_source(source_items, requested_source_id)
                if selected is None:
                    raise HTTPException(status_code=404, detail="store_source_not_found_or_disabled")
                source_id = selected.id
                debug_source_id = source_id
                debug_resolved_base_url = _resolved_base_url_for_source(cache_catalog, source_id, selected.base_url)
                index_payload, publishers_payload = cache_catalog.load_cached_documents(selected.id)
                if index_payload is None:
                    raise HTTPException(status_code=400, detail="catalog_cache_missing")

                addon_item, release_candidates = _resolve_catalog_release(
                    index_payload=index_payload,
                    addon_id=body.addon_id.strip(),
                    version=body.version,
                )
                core_version = _configured_core_version()
                did_refresh_retry = False
                while True:
                    release_item: dict[str, Any] | None = None
                    manifest = None
                    compatibility_failures: list[dict[str, Any]] = []
                    for candidate in release_candidates:
                        candidate_manifest = _build_release_manifest(body.addon_id.strip(), addon_item, candidate)
                        if body.version and body.version.strip():
                            manifest = candidate_manifest
                            release_item = candidate
                            break
                        try:
                            resolve_manifest_compatibility(
                                candidate_manifest,
                                core_version=core_version,
                                installed_addons=installed_addons_with_versions(registry),
                            )
                            manifest = candidate_manifest
                            release_item = candidate
                            break
                        except ResolverError as exc:
                            compatibility_failures.append(
                                {
                                    "version": str(candidate.get("version") or ""),
                                    "error": exc.to_dict().get("error", {"code": exc.code, "message": exc.message}),
                                }
                            )
                            continue
                    if manifest is None or release_item is None:
                        if compatibility_failures:
                            raise HTTPException(
                                status_code=409,
                                detail={
                                    "error": "catalog_no_compatible_release",
                                    "core_version": core_version,
                                    "reasons": compatibility_failures,
                                },
                            )
                        raise HTTPException(status_code=409, detail="catalog_no_compatible_release")
                    debug_package_profile = manifest.package_profile
                    catalog_package_profile = _release_package_profile(addon_item, release_item)
                    if manifest.package_profile != catalog_package_profile:
                        release_url = _release_artifact_url(release_item)
                        if release_url:
                            debug_artifact_url = release_url
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "error": "catalog_manifest_profile_mismatch",
                                "source_id": source_id,
                                "resolved_base_url": debug_resolved_base_url,
                                "artifact_url": release_url or None,
                                "version": manifest.version,
                                "expected_package_profile": catalog_package_profile,
                                "detected_package_profile": manifest.package_profile,
                                "hint": (
                                    "catalog release package_profile must match manifest package_profile; "
                                    "align both fields to the same profile before install"
                                ),
                            },
                        )
                    release_signature_b64 = _release_signature_b64(release_item)
                    publisher_key_id = str(release_item.get("publisher_key_id") or "").strip()
                    if not publisher_key_id:
                        raise HTTPException(status_code=400, detail="catalog_publisher_key_missing")
                    debug_publisher_key_id = publisher_key_id
                    publisher_key = _publisher_key_from_payload(
                        publishers_payload,
                        publisher_id=manifest.publisher_id,
                        publisher_key_id=publisher_key_id,
                    )
                    if publisher_key is None:
                        raise HTTPException(status_code=400, detail="catalog_publisher_key_not_found_or_disabled")
                    public_key_pem, key_signature_type = publisher_key
                    release_signature_type = _release_signature_type(release_item)
                    debug_signature_type = release_signature_type
                    if key_signature_type != release_signature_type:
                        raise HTTPException(status_code=400, detail="catalog_signature_type_mismatch")

                    source_release_url = _release_artifact_url(release_item)
                    if not source_release_url:
                        raise HTTPException(status_code=400, detail="catalog_artifact_url_missing")
                    debug_artifact_url = source_release_url

                    await audit_store.record(
                        action="catalog_download",
                        addon_id=manifest.id,
                        version=manifest.version,
                        status="started",
                        message=source_release_url,
                        actor=actor,
                    )
                    try:
                        artifact_bytes = cache_catalog.download_artifact(source_release_url)
                        break
                    except Exception as exc:
                        if str(exc) == "catalog_http_error:404" and did_refresh_retry:
                            raise HTTPException(
                                status_code=409,
                                detail={
                                    "error": "catalog_artifact_unavailable",
                                    "artifact_url": source_release_url,
                                    "source_id": source_id,
                                    "retry_after_refresh": True,
                                },
                            )
                        if str(exc) != "catalog_http_error:404":
                            raise
                        refresh = cache_catalog.refresh_source(selected)
                        if not bool(refresh.get("ok")):
                            raise RuntimeError(
                                str(refresh.get("catalog_status", {}).get("last_error_message") or "catalog_refresh_failed")
                            )
                        refresh_status = refresh.get("catalog_status", {})
                        if isinstance(refresh_status, dict):
                            refresh_resolved = str(refresh_status.get("resolved_base_url") or "").strip()
                            if refresh_resolved:
                                debug_resolved_base_url = refresh_resolved
                            else:
                                debug_resolved_base_url = _resolved_base_url_for_source(
                                    cache_catalog,
                                    source_id,
                                    debug_resolved_base_url or selected.base_url,
                                )
                        index_payload, publishers_payload = cache_catalog.load_cached_documents(selected.id)
                        if index_payload is None:
                            raise HTTPException(status_code=400, detail="catalog_cache_missing")
                        addon_item, release_candidates = _resolve_catalog_release(
                            index_payload=index_payload,
                            addon_id=body.addon_id.strip(),
                            version=body.version,
                        )
                        did_refresh_retry = True
                actual_sha256 = _hex_sha256(artifact_bytes)
                expected_sha256_candidates = _release_checksum_candidates(release_item, manifest.checksum)
                expected_sha256 = expected_sha256_candidates[0] if expected_sha256_candidates else ""
                debug_expected_sha256 = expected_sha256_candidates
                debug_actual_sha256 = actual_sha256
                checksum_match = any(hmac.compare_digest(actual_sha256, candidate) for candidate in expected_sha256_candidates)
                if not checksum_match:
                    log.error(
                        "Catalog sha256 mismatch addon_id=%s version=%s source_id=%s release_url=%s expected=%s actual=%s",
                        manifest.id,
                        manifest.version,
                        source_id,
                        source_release_url,
                        expected_sha256_candidates,
                        actual_sha256,
                    )
                    await audit_store.record(
                        action="catalog_verify",
                        addon_id=manifest.id,
                        version=manifest.version,
                        status="failed",
                        message="catalog_sha256_mismatch",
                        actor=actor,
                    )
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "catalog_sha256_mismatch",
                            "source_id": source_id,
                            "artifact_url": source_release_url,
                            "expected_sha256": expected_sha256_candidates,
                            "actual_sha256": actual_sha256,
                        },
                    )
                await audit_store.record(
                    action="catalog_download",
                    addon_id=manifest.id,
                    version=manifest.version,
                    status="success",
                    message="download_completed",
                    actor=actor,
                )

                temp_install_dir = Path(tempfile.mkdtemp(prefix=f"store-install-{manifest.id}-", dir=str(Path(tempfile.gettempdir()))))
                package_path = temp_install_dir / _artifact_temp_filename(source_release_url)
                package_path.write_bytes(artifact_bytes)

            if source_id == "local":
                verify_release_artifact(manifest, artifact_bytes, public_key_pem)
            else:
                verify_detached_artifact_signature(
                    artifact_bytes=artifact_bytes,
                    signature_b64=release_signature_b64 or "",
                    public_key_pem=public_key_pem,
                    signature_type=release_signature_type,
                )
            await audit_store.record(
                action="catalog_verify" if source_id != "local" else "install_verify",
                addon_id=manifest.id,
                version=manifest.version,
                status="success",
                message="signature_and_checksum_verified",
                actor=actor,
            )

            resolve_manifest_compatibility(
                manifest,
                core_version=_configured_core_version(),
                installed_addons=installed_addons_with_versions(registry),
            )

            if manifest.package_profile != "embedded_addon":
                error_payload: dict[str, Any] = {
                    "error": "catalog_package_profile_unsupported" if catalog_install else "package_profile_unsupported",
                    "package_profile": manifest.package_profile,
                    "supported_profiles": ["embedded_addon"],
                    "hint": (
                        "standalone_service packages are not installable as embedded addons; "
                        "deploy service package externally and register via /api/admin/addons/registry"
                    ),
                }
                if catalog_install:
                    error_payload["source_id"] = debug_source_id
                    error_payload["resolved_base_url"] = debug_resolved_base_url
                    error_payload["artifact_url"] = debug_artifact_url
                raise HTTPException(status_code=400, detail=error_payload)

            result = _atomic_install_or_update(
                manifest=manifest,
                package_path=package_path,
                allow_replace=False,
            )

            if body.enable:
                registry.set_enabled(manifest.id, True)

            install_state = {
                "installed_version": manifest.version,
                "installed_from_source_id": source_id,
                "installed_resolved_base_url": debug_resolved_base_url,
                "installed_release_url": source_release_url,
                "installed_sha256": expected_sha256,
                "installed_at": _utcnow_iso(),
                "last_install_error": None,
            }
            _set_install_state(manifest.id, install_state)

            await audit_store.record(
                action="install",
                addon_id=manifest.id,
                version=manifest.version,
                status="success",
                message="install_completed",
                actor=actor,
            )
            return {
                "ok": True,
                "addon_id": manifest.id,
                "version": manifest.version,
                "installed_path": str(result.addon_dir),
                "enabled": registry.is_enabled(manifest.id),
                "registry_loaded": manifest.id in registry.addons,
                # TODO(phase3): report true hot-reload runtime status once dynamic module reload is supported.
                "hot_loaded": False,
                "installed_from_source_id": source_id,
                "installed_resolved_base_url": debug_resolved_base_url,
                "installed_release_url": source_release_url,
                "installed_sha256": expected_sha256,
            }
        except VerificationError as exc:
            _persist_last_install_error(
                error_code=exc.code,
                publisher_key_id=debug_publisher_key_id,
                signature_type=debug_signature_type,
            )
            await audit_store.record(
                action="install",
                addon_id=(body.manifest.id if body.manifest is not None else (body.addon_id or "__unknown__")),
                version=(body.manifest.version if body.manifest is not None else body.version),
                status="failed",
                message=exc.code,
                actor=actor,
            )
            detail_payload = exc.to_dict()
            if catalog_install:
                err_payload = detail_payload.get("error")
                if isinstance(err_payload, dict):
                    raw_details = err_payload.get("details")
                    details = dict(raw_details) if isinstance(raw_details, dict) else {}
                    if debug_source_id:
                        details["source_id"] = debug_source_id
                    if debug_resolved_base_url:
                        details["resolved_base_url"] = debug_resolved_base_url
                    if debug_artifact_url:
                        details["artifact_url"] = debug_artifact_url
                    if debug_publisher_key_id:
                        details["publisher_key_id"] = debug_publisher_key_id
                    if debug_signature_type:
                        details["signature_type"] = debug_signature_type
                    if exc.code == "signature_invalid":
                        details["hint"] = "release_sig must match downloaded artifact bytes for this artifact_url"
                    if details:
                        err_payload["details"] = details
            raise HTTPException(status_code=400, detail=detail_payload)
        except ResolverError as exc:
            _persist_last_install_error(error_code=exc.code)
            await audit_store.record(
                action="install",
                addon_id=(body.manifest.id if body.manifest is not None else (body.addon_id or "__unknown__")),
                version=(body.manifest.version if body.manifest is not None else body.version),
                status="failed",
                message=exc.code,
                actor=actor,
            )
            raise HTTPException(status_code=409, detail=exc.to_dict())
        except HTTPException as exc:
            detail_source_id: str | None = None
            detail_artifact_url: str | None = None
            detail_expected_sha256: list[str] | None = None
            detail_actual_sha256: str | None = None
            error_code: str | None = None
            detail_payload = exc.detail
            if isinstance(detail_payload, dict):
                error_code = str(detail_payload.get("error") or detail_payload.get("code") or "").strip() or None
                detail_source_id = str(detail_payload.get("source_id") or "").strip() or None
                detail_artifact_url = str(detail_payload.get("artifact_url") or "").strip() or None
                detail_actual_sha256 = str(detail_payload.get("actual_sha256") or "").strip() or None
                raw_expected = detail_payload.get("expected_sha256")
                if isinstance(raw_expected, list):
                    detail_expected_sha256 = [str(item).strip() for item in raw_expected if str(item).strip()]
                elif isinstance(raw_expected, str) and raw_expected.strip():
                    detail_expected_sha256 = [raw_expected.strip()]
            elif isinstance(detail_payload, str) and detail_payload.strip():
                error_code = detail_payload.strip()
            _persist_last_install_error(
                error_code=error_code,
                source_id=detail_source_id,
                artifact_url=detail_artifact_url,
                expected_sha256=detail_expected_sha256,
                actual_sha256=detail_actual_sha256,
            )
            await audit_store.record(
                action="install",
                addon_id=(body.manifest.id if body.manifest is not None else (body.addon_id or "__unknown__")),
                version=(body.manifest.version if body.manifest is not None else body.version),
                status="failed",
                message=str(exc.detail),
                actor=actor,
            )
            raise
        except Exception as exc:
            await audit_store.record(
                action="install",
                addon_id=(body.manifest.id if body.manifest is not None else (body.addon_id or "__unknown__")),
                version=(body.manifest.version if body.manifest is not None else body.version),
                status="failed",
                message=type(exc).__name__,
                actor=actor,
            )
            detail = str(exc) or type(exc).__name__
            if detail == "addon_already_installed":
                raise HTTPException(status_code=409, detail=detail)
            if catalog_install and detail.startswith("missing_backend_entrypoint"):
                layout_hint = None
                if detail == "missing_backend_entrypoint:service_layout_app_main":
                    layout_hint = "service_layout_app_main"
                error_payload: dict[str, Any] = {
                    "error": "catalog_package_layout_invalid",
                    "reason": "missing_backend_entrypoint",
                    "source_id": debug_source_id,
                    "resolved_base_url": debug_resolved_base_url,
                    "artifact_url": debug_artifact_url,
                    "expected_package_profile": debug_package_profile or "embedded_addon",
                    "expected_backend_entrypoint": "backend/addon.py",
                }
                if layout_hint == "service_layout_app_main":
                    error_payload["layout_hint"] = layout_hint
                    error_payload["detected_package_profile"] = "standalone_service"
                    error_payload["hint"] = (
                        "artifact appears to be a standalone service package (app/main.py); "
                        "set package_profile=standalone_service and deploy/register externally, "
                        "or ship embedded_addon layout with backend/addon.py"
                    )
                _persist_last_install_error(error_code="catalog_package_layout_invalid")
                raise HTTPException(status_code=400, detail=error_payload)
            _persist_last_install_error(error_code=detail)
            raise HTTPException(status_code=400, detail=detail)
        finally:
            if temp_install_dir is not None:
                shutil.rmtree(temp_install_dir, ignore_errors=True)

    @router.post("/update")
    async def update_addon(
        body: StoreUpdateRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
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
                core_version=_configured_core_version(),
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
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
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
            _clear_install_state(addon_id)
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
        install_state = _get_install_state(addon_id) or {}
        last_install_error = install_state.get("last_install_error")
        if not isinstance(last_install_error, dict):
            last_install_error = None

        return {
            "ok": True,
            "addon_id": addon_id,
            "installed": target.exists(),
            "loaded": addon_id in registry.addons,
            "enabled": registry.is_enabled(addon_id),
            "version": version or (registry.addons[addon_id].meta.version if addon_id in registry.addons else None),
            "installed_version": install_state.get("installed_version"),
            "installed_from_source_id": install_state.get("installed_from_source_id"),
            "installed_resolved_base_url": install_state.get("installed_resolved_base_url"),
            "installed_release_url": install_state.get("installed_release_url"),
            "installed_sha256": install_state.get("installed_sha256"),
            "installed_at": install_state.get("installed_at"),
            "last_install_error": last_install_error,
        }

    @router.get("/admin/audit")
    async def store_audit_list(
        request: Request,
        addon_id: str | None = Query(default=None),
        action: str | None = Query(default=None),
        status: str | None = Query(default=None),
        from_ts: str | None = Query(default=None),
        to_ts: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        return await audit_store.list_rows(
            addon_id=addon_id,
            action=action,
            status=status,
            from_ts=from_ts,
            to_ts=to_ts,
            page=page,
            page_size=page_size,
        )

    return router

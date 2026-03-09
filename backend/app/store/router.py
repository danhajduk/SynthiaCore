from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Query, Request

from app.addons.registry import AddonRegistry
from app.api.admin import require_admin_token
from app.system.events import PlatformEventService
from app.system.runtime import StandaloneRuntimeService
from .audit import StoreAuditLogStore
from .catalog import CatalogCacheClient, CatalogQuery, StaticCatalogStore
from . import lifecycle as lifecycle_mod
from .extract import extract_package, find_addon_dir
from .lifecycle import (
    AtomicResult,
    StoreInstallRequest,
    StoreStandaloneUpdateRequest,
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
from .models import DockerGroupDeclaration, ReleaseManifest, RuntimeDefaults
from .resolver import ResolverError, resolve_manifest_compatibility
from .signing import VerificationError, verify_release_artifact
from .standalone_desired import SSAPDesiredValidationError, build_desired_state, write_desired_state_atomic
from .standalone_paths import service_addon_dir, service_version_dir
from .sources import StoreSource, StoreSourcesStore

log = logging.getLogger("synthia.store")
CATALOG_RELEASE_VERSION_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
CATALOG_RELEASE_VERSION_SUFFIX_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"[A-Za-z][0-9A-Za-z]*$"
)

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


def _install_error_summary() -> dict[str, Any]:
    state = _load_install_state()
    counts: dict[str, int] = {}
    with_error = 0
    for value in state.values():
        if not isinstance(value, dict):
            continue
        err = value.get("last_install_error")
        if not isinstance(err, dict):
            continue
        code = str(err.get("error") or "unknown").strip() or "unknown"
        counts[code] = counts.get(code, 0) + 1
        with_error += 1
    top_errors = [
        {"code": code, "count": count}
        for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "ok": True,
        "tracked_addons": len(state),
        "addons_with_errors": with_error,
        "top_errors": top_errors,
    }


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


def _configured_core_version() -> str:
    return os.getenv("SYNTHIA_CORE_VERSION", "0.1.0")


def _abs_path_str(path: Path | str | None) -> str | None:
    if path is None:
        return None
    return str(Path(path).resolve())


def _compose_safe_project_name(value: str | None, addon_id: str) -> str:
    raw_value = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9_-]+", "-", raw_value).strip("-_")
    if normalized and re.match(r"^[a-z0-9]", normalized):
        return normalized
    fallback = re.sub(r"[^a-z0-9_-]+", "-", str(addon_id).strip().lower()).strip("-_")
    if fallback and re.match(r"^[a-z0-9]", fallback):
        return f"synthia-addon-{fallback}"
    return "synthia-addon-service"


def _stage_standalone_artifact(
    addon_id: str,
    version: str,
    artifact_bytes: bytes,
) -> Path:
    version_dir = service_version_dir(addon_id, version, create=True)
    staged_artifact_path = version_dir / "addon.tgz"
    staged_artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = staged_artifact_path.with_suffix(staged_artifact_path.suffix + ".tmp")
    tmp_path.write_bytes(artifact_bytes)
    tmp_path.replace(staged_artifact_path)
    return staged_artifact_path


def _runtime_defaults_from_artifact(package_path: Path, addon_id: str) -> RuntimeDefaults | None:
    try:
        with tempfile.TemporaryDirectory(prefix="store-runtime-defaults-") as tmp:
            extract_dir = Path(tmp) / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)
            extract_package(package_path, extract_dir)
            addon_dir = find_addon_dir(extract_dir, addon_id)
            manifest_path = addon_dir / "manifest.json"
            if not manifest_path.exists():
                return None
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return None
            defaults_raw = raw.get("runtime_defaults")
            if not isinstance(defaults_raw, dict):
                return None
            return RuntimeDefaults.model_validate(defaults_raw)
    except Exception:
        return None


def _docker_groups_from_artifact(package_path: Path, addon_id: str) -> list[DockerGroupDeclaration] | None:
    try:
        with tempfile.TemporaryDirectory(prefix="store-docker-groups-") as tmp:
            extract_dir = Path(tmp) / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)
            extract_package(package_path, extract_dir)
            addon_dir = find_addon_dir(extract_dir, addon_id)
            manifest_path = addon_dir / "manifest.json"
            if not manifest_path.exists():
                return None
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return None
            groups_raw = raw.get("docker_groups")
            if not isinstance(groups_raw, list):
                return None
            out: list[DockerGroupDeclaration] = []
            for item in groups_raw:
                if not isinstance(item, dict):
                    continue
                out.append(DockerGroupDeclaration.model_validate(item))
            return out
    except Exception:
        return None


def _docker_groups_from_service(addon_id: str, pinned_version: str | None) -> list[DockerGroupDeclaration] | None:
    service_dir = service_addon_dir(addon_id, create=False)
    candidate_paths = []
    if pinned_version:
        candidate_paths.append(service_dir / "versions" / pinned_version / "extracted" / "manifest.json")
    candidate_paths.extend(
        [
            service_dir / "current" / "extracted" / "manifest.json",
            service_dir / "current" / "manifest.json",
            service_dir / "manifest.json",
        ]
    )
    for path in candidate_paths:
        if not path.exists():
            continue
        raw = _load_json_file(path)
        if not isinstance(raw, dict):
            continue
        groups_raw = raw.get("docker_groups")
        if not isinstance(groups_raw, list):
            continue
        out: list[DockerGroupDeclaration] = []
        for item in groups_raw:
            if not isinstance(item, dict):
                continue
            out.append(DockerGroupDeclaration.model_validate(item))
        return out
    return None


def _normalize_enabled_docker_groups(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _validate_requested_docker_groups(requested: list[str], declared: list[DockerGroupDeclaration]) -> None:
    if not requested:
        return
    allowed = {item.name for item in declared if str(item.name).strip()}
    if not allowed:
        raise HTTPException(
            status_code=400,
            detail={"error": "docker_groups_not_declared", "requested_docker_groups": requested},
        )
    unknown = sorted([item for item in requested if item not in allowed])
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "docker_groups_unknown",
                "unknown_docker_groups": unknown,
                "declared_docker_groups": sorted(allowed),
            },
        )


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(raw, dict):
        return raw
    return None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _standalone_compose_file(service_dir: Path, active_version: str | None) -> Path | None:
    current_compose = service_dir / "current" / "docker-compose.yml"
    if current_compose.exists():
        return current_compose
    if active_version:
        version_compose = service_dir / "versions" / active_version / "docker-compose.yml"
        if version_compose.exists():
            return version_compose
    versions_dir = service_dir / "versions"
    if versions_dir.exists():
        for candidate in sorted(versions_dir.glob("*/docker-compose.yml"), reverse=True):
            if candidate.exists():
                return candidate
    return None


def _uninstall_standalone_service(addon_id: str) -> dict[str, Any]:
    service_dir = service_addon_dir(addon_id, create=False)
    if not service_dir.exists():
        return {"removed": False, "reason": "standalone_not_installed"}

    desired_path = service_dir / "desired.json"
    runtime_path = service_dir / "runtime.json"
    desired_payload = _load_json_file(desired_path) or {}
    runtime_payload = _load_json_file(runtime_path) or {}

    runtime_cfg = desired_payload.get("runtime") if isinstance(desired_payload.get("runtime"), dict) else {}
    project_name = str(runtime_cfg.get("project_name") or f"synthia-addon-{addon_id}").strip() or f"synthia-addon-{addon_id}"
    active_version = str(runtime_payload.get("active_version") or "").strip() or None
    compose_file = _standalone_compose_file(service_dir, active_version)

    if desired_payload:
        desired_payload["desired_state"] = "stopped"
        _write_json_atomic(desired_path, desired_payload)

    compose_down_error: str | None = None
    removed_image_ids: list[str] = []
    image_remove_error: str | None = None
    compose_image_ids: list[str] = []
    if compose_file is not None:
        try:
            images_proc = subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "-p", project_name, "images", "-q"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if images_proc.returncode == 0:
                compose_image_ids = sorted({line.strip() for line in (images_proc.stdout or "").splitlines() if line.strip()})
        except Exception:
            compose_image_ids = []
        try:
            proc = subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "-p", project_name, "down", "--remove-orphans"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if proc.returncode != 0:
                compose_down_error = (proc.stderr or proc.stdout or f"exit_{proc.returncode}").strip() or f"exit_{proc.returncode}"
        except Exception as exc:
            compose_down_error = str(exc) or type(exc).__name__
        if compose_image_ids:
            try:
                rm_proc = subprocess.run(
                    ["docker", "image", "rm", "-f", *compose_image_ids],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                if rm_proc.returncode != 0:
                    image_remove_error = (rm_proc.stderr or rm_proc.stdout or f"exit_{rm_proc.returncode}").strip() or f"exit_{rm_proc.returncode}"
                else:
                    removed_image_ids = compose_image_ids
            except Exception as exc:
                image_remove_error = str(exc) or type(exc).__name__

    shutil.rmtree(service_dir, ignore_errors=False)
    return {
        "removed": True,
        "compose_file": _abs_path_str(compose_file),
        "project_name": project_name,
        "compose_down_error": compose_down_error,
        "removed_image_ids": removed_image_ids,
        "image_remove_error": image_remove_error,
    }


def _read_standalone_runtime(
    addon_id: str,
    runtime_service: StandaloneRuntimeService | None = None,
) -> dict[str, Any]:
    runtime = runtime_service or StandaloneRuntimeService()
    snapshot = runtime.get_standalone_addon_runtime_snapshot(addon_id)
    runtime_data = snapshot.runtime.model_dump(mode="python")
    raw_runtime = snapshot.raw_runtime if isinstance(snapshot.raw_runtime, dict) else None
    health_payload = None
    if raw_runtime is not None:
        health_payload = raw_runtime.get("health")
    if health_payload is None and runtime_data.get("health_status") != "unknown":
        health_payload = {
            "status": runtime_data.get("health_status"),
            "detail": runtime_data.get("health_detail"),
        }

    payload: dict[str, Any] = {
        "runtime_path": snapshot.runtime_path,
        "runtime_state": runtime_data.get("runtime_state") or "unknown",
        "standalone_runtime": (
            {
                "state": runtime_data.get("runtime_state") or "unknown",
                "active_version": (
                    raw_runtime.get("active_version")
                    if raw_runtime is not None
                    else runtime_data.get("active_version")
                ),
                "target_version": runtime_data.get("target_version"),
                "last_action": raw_runtime.get("last_action") if raw_runtime is not None else None,
                "health": health_payload,
                "error": (
                    raw_runtime.get("error")
                    if raw_runtime is not None
                    else runtime_data.get("last_error")
                ),
                "last_error": (
                    raw_runtime.get("last_error")
                    if raw_runtime is not None
                    else runtime_data.get("last_error")
                ),
                "previous_version": (
                    raw_runtime.get("previous_version")
                    if raw_runtime is not None
                    else None
                ),
                "container_name": runtime_data.get("container_name"),
                "container_status": runtime_data.get("container_status"),
                "running": runtime_data.get("running"),
                "restart_count": runtime_data.get("restart_count"),
                "started_at": runtime_data.get("started_at"),
                "published_ports": runtime_data.get("published_ports") or [],
                "network": runtime_data.get("network"),
            }
            if raw_runtime is not None
            else None
        ),
    }
    if snapshot.runtime_error:
        payload["runtime_error"] = snapshot.runtime_error
    if snapshot.docker_error:
        payload["docker_error"] = snapshot.docker_error
    if snapshot.desired_error:
        payload["desired_error"] = snapshot.desired_error
    return payload


def _runtime_error_summary(runtime_payload: dict[str, Any]) -> str | None:
    runtime = runtime_payload.get("standalone_runtime")
    if not isinstance(runtime, dict):
        return None
    last_error = str(runtime.get("last_error") or runtime.get("error") or "").strip()
    if not last_error:
        return None
    if ":" in last_error:
        return last_error.split(":", 1)[1].strip() or last_error
    return last_error


def _standalone_ui_redirect_info(addon_id: str, runtime_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_state = str(runtime_payload.get("runtime_state") or "unknown").strip() or "unknown"
    ui_embed_target = f"/ui/addons/{addon_id}"
    runtime = runtime_payload.get("standalone_runtime")
    if not isinstance(runtime, dict):
        return {
            "ui_reachable": False,
            "ui_redirect_target": None,
            "ui_embed_target": ui_embed_target,
            "ui_reason": "runtime_unavailable",
        }
    published_ports = runtime.get("published_ports")
    ports = [str(item).strip() for item in published_ports] if isinstance(published_ports, list) else []
    ports = [item for item in ports if item]
    health = runtime.get("health")
    health_status = ""
    if isinstance(health, dict):
        health_status = str(health.get("status") or "").strip().lower()
    unhealthy = health_status in {"unhealthy", "error", "failing", "fail"}
    reachable = runtime_state == "running" and bool(ports) and not unhealthy
    reason = "ready" if reachable else (
        "runtime_not_running"
        if runtime_state != "running"
        else ("health_unhealthy" if unhealthy else "no_published_ports")
    )
    return {
        "ui_reachable": reachable,
        "ui_redirect_target": f"/addons/{addon_id}" if reachable else None,
        "ui_embed_target": ui_embed_target,
        "ui_reason": reason,
    }


def _standalone_retention_diagnostics(addon_id: str, runtime_payload: dict[str, Any]) -> dict[str, Any]:
    keep_versions_raw = str(os.environ.get("SYNTHIA_SUPERVISOR_KEEP_VERSIONS", "")).strip()
    try:
        keep_versions = int(keep_versions_raw) if keep_versions_raw else 3
    except Exception:
        keep_versions = 3
    keep_versions = max(keep_versions, 2)

    versions_root = service_addon_dir(addon_id, create=False) / "versions"
    version_entries: list[tuple[str, float]] = []
    if versions_root.exists():
        for entry in versions_root.iterdir():
            if not entry.is_dir():
                continue
            try:
                mtime = entry.stat().st_mtime
            except Exception:
                mtime = 0.0
            version_entries.append((entry.name, mtime))
    version_entries.sort(key=lambda item: item[1], reverse=True)
    available_versions = [name for name, _mtime in version_entries]

    runtime = runtime_payload.get("standalone_runtime")
    active_version = None
    previous_version = None
    if isinstance(runtime, dict):
        active_version = str(runtime.get("active_version") or "").strip() or None
        previous_version = str(runtime.get("previous_version") or "").strip() or None

    retained: list[str] = []
    for candidate in (active_version, previous_version):
        if candidate and candidate not in retained:
            retained.append(candidate)
    for version in available_versions:
        if len(retained) >= keep_versions:
            break
        if version not in retained:
            retained.append(version)
    prunable_versions = [name for name in available_versions if name not in retained]

    return {
        "keep_versions": keep_versions,
        "active_version": active_version,
        "previous_version": previous_version,
        "available_versions": available_versions,
        "retained_versions": retained,
        "prunable_versions": prunable_versions,
    }


def _registry_state_for_addon(registry: AddonRegistry, addon_id: str) -> str:
    addon = registry.addons.get(addon_id)
    if addon is None:
        return "unknown"
    return str(getattr(addon, "health_status", None) or "registered")


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


def _normalize_install_mode(value: Any) -> str:
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
    runtime_defaults = release_item.get("runtime_defaults") or addon_item.get("runtime_defaults")
    docker_groups = release_item.get("docker_groups") or addon_item.get("docker_groups") or []

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
        data.setdefault("runtime_defaults", runtime_defaults)
        data.setdefault("docker_groups", docker_groups)
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
            "runtime_defaults": runtime_defaults,
            "docker_groups": docker_groups,
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
    def _is_enabled(enabled_flag: Any, status_value: Any) -> bool:
        if enabled_flag is True:
            return True
        if enabled_flag is False:
            return False
        status = str(status_value or "enabled").strip().lower()
        if status in {"enabled", "active", "ok"}:
            return True
        if status in {"disabled", "revoked", "inactive", "blocked"}:
            return False
        return True

    def _to_pem(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        text = value.strip()
        if not text:
            return ""
        if "BEGIN PUBLIC KEY" in text:
            return text
        compact = "".join(text.split())
        if not compact:
            return ""
        lines = [compact[i : i + 64] for i in range(0, len(compact), 64)]
        return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----"

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
        if not _is_enabled(pub.get("enabled"), pub.get("status")):
            continue
        keys = pub.get("keys")
        if isinstance(keys, list):
            for item in keys:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or item.get("key_id") or "").strip()
                if item_id != publisher_key_id:
                    continue
                if not _is_enabled(item.get("enabled"), item.get("status")):
                    continue
                pem = _to_pem(item.get("public_key_pem") or item.get("pem") or item.get("public_key"))
                if isinstance(pem, str) and pem.strip():
                    sig_type = str(
                        item.get("signature_type") or item.get("type") or item.get("algorithm") or "rsa-sha256"
                    ).strip().lower()
                    return pem, sig_type
        # Backward-compat shape: publisher carries a single key directly.
        if str(pub.get("key_id", "")).strip() == publisher_key_id:
            pem = _to_pem(pub.get("public_key_pem") or pub.get("pem") or pub.get("public_key"))
            if isinstance(pem, str) and pem.strip():
                sig_type = str(pub.get("signature_type") or pub.get("type") or pub.get("algorithm") or "rsa-sha256").strip().lower()
                return pem, sig_type
    return None


def _publisher_display_name_map(publishers_payload: Any) -> dict[str, str]:
    if not isinstance(publishers_payload, dict):
        return {}
    publishers = publishers_payload.get("publishers")
    if not isinstance(publishers, list):
        return {}
    out: dict[str, str] = {}
    for pub in publishers:
        if not isinstance(pub, dict):
            continue
        pub_id = str(pub.get("id") or pub.get("publisher_id") or "").strip()
        if not pub_id:
            continue
        display_name = str(pub.get("display_name") or pub.get("name") or "").strip()
        if not display_name:
            continue
        out[pub_id] = display_name
    return out


def _apply_publisher_display_names(items_payload: Any, publishers_payload: Any) -> None:
    if not isinstance(items_payload, list):
        return
    display_names = _publisher_display_name_map(publishers_payload)
    if not display_names:
        return
    for item in items_payload:
        if not isinstance(item, dict):
            continue
        publisher_id = str(item.get("publisher_id") or "").strip()
        if not publisher_id:
            continue
        display_name = display_names.get(publisher_id)
        if display_name is None and "#" in publisher_id:
            display_name = display_names.get(publisher_id.split("#", 1)[0].strip())
        if display_name:
            item["publisher_display_name"] = display_name


def _resolve_catalog_release(
    index_payload: Any,
    addon_id: str,
    version: str | None,
    channel: str | None = None,
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
    requested_channel = str(channel or "stable").strip().lower() or "stable"
    channels = addon_item.get("channels")
    if isinstance(channels, dict):
        if version and version.strip():
            channel_names = [str(name) for name in channels.keys()]
        else:
            if requested_channel not in channels:
                raise RuntimeError("catalog_channel_not_found")
            channel_names = [requested_channel]
        for channel_name in channel_names:
            entries = _channel_release_entries(channels.get(channel_name))
            for item in entries:
                row = dict(item)
                row.setdefault("channel", channel_name)
                release_items.append(row)

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

    release_items.sort(key=lambda r: _parse_semver_key(str(r.get("version", ""))), reverse=True)
    return addon_item, release_items


def _catalog_release_entries(addon_item: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    entries: list[tuple[str, dict[str, Any]]] = []
    releases = addon_item.get("releases")
    if isinstance(releases, list):
        for idx, rel in enumerate(releases):
            if isinstance(rel, dict):
                entries.append((f"releases[{idx}]", rel))
    channels = addon_item.get("channels")
    if isinstance(channels, dict):
        for channel_name, raw_channel in channels.items():
            rows: list[dict[str, Any]] = []
            if isinstance(raw_channel, list):
                rows = [item for item in raw_channel if isinstance(item, dict)]
            elif isinstance(raw_channel, dict):
                wrapped = raw_channel.get("releases")
                if isinstance(wrapped, list):
                    rows = [item for item in wrapped if isinstance(item, dict)]
                elif "version" in raw_channel:
                    rows = [raw_channel]
            for idx, rel in enumerate(rows):
                entries.append((f"channels.{channel_name}[{idx}]", rel))
    return entries


def _release_version_valid(version: str) -> bool:
    return bool(
        CATALOG_RELEASE_VERSION_RE.fullmatch(version)
        or CATALOG_RELEASE_VERSION_SUFFIX_RE.fullmatch(version)
    )


def _validate_catalog_index_payload(index_payload: Any) -> dict[str, Any]:
    addons = _extract_catalog_items(index_payload)
    issues: list[dict[str, str]] = []
    checked_releases = 0
    for addon_idx, addon in enumerate(addons):
        addon_id = str(addon.get("id") or addon.get("addon_id") or f"addon[{addon_idx}]").strip() or f"addon[{addon_idx}]"
        releases = _catalog_release_entries(addon)
        if not releases:
            issues.append(
                {
                    "code": "catalog_releases_missing",
                    "addon_id": addon_id,
                    "path": "releases",
                    "message": "addon entry has no releases/channels release entries",
                }
            )
            continue
        for path, rel in releases:
            checked_releases += 1
            version = str(rel.get("version") or "").strip()
            if not version:
                issues.append(
                    {
                        "code": "catalog_release_version_missing",
                        "addon_id": addon_id,
                        "path": path,
                        "message": "release entry is missing version",
                    }
                )
                continue
            if not _release_version_valid(version):
                issues.append(
                    {
                        "code": "catalog_release_version_invalid",
                        "addon_id": addon_id,
                        "path": path,
                        "message": (
                            f"invalid version '{version}' (expected semver or semver+suffix)"
                        ),
                    }
                )
    return {
        "ok": True,
        "valid": len(issues) == 0,
        "checked_addons": len(addons),
        "checked_releases": checked_releases,
        "issues": issues,
    }


def build_store_router(
    registry: AddonRegistry,
    audit_store: StoreAuditLogStore,
    sources_store: StoreSourcesStore | None = None,
    catalog_client: CatalogCacheClient | None = None,
    runtime_service: StandaloneRuntimeService | None = None,
    events: PlatformEventService | None = None,
    mqtt_approval_service=None,
) -> APIRouter:
    router = APIRouter()
    static_catalog = StaticCatalogStore.from_default_path()
    cache_catalog = catalog_client or CatalogCacheClient.from_default_path()
    sources = sources_store
    standalone_runtime = runtime_service or StandaloneRuntimeService()

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
                load_cached_docs = getattr(cache_catalog, "load_cached_documents", None)
                if callable(load_cached_docs):
                    try:
                        _, publishers_payload = load_cached_docs(selected.id)
                    except Exception:
                        publishers_payload = None
                    _apply_publisher_display_names(payload.get("items"), publishers_payload)
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

    @router.get("/sources/{source_id}/validate")
    async def validate_store_source(source_id: str, request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        if sources is None:
            raise HTTPException(status_code=500, detail="sources_store_not_configured")
        source_items = await sources.list_sources()
        selected = cache_catalog.select_source(source_items, source_id)
        if selected is None:
            raise HTTPException(status_code=404, detail="source_not_found")
        index_payload, _publishers_payload = cache_catalog.load_cached_documents(selected.id)
        if index_payload is None:
            raise HTTPException(status_code=400, detail="catalog_cache_missing")
        result = _validate_catalog_index_payload(index_payload)
        result["source_id"] = selected.id
        return result

    @router.post("/install")
    async def install_addon(
        body: StoreInstallRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        actor = body.actor or "admin_token"
        requested_install_mode = _normalize_install_mode(body.install_mode)
        if requested_install_mode not in {"embedded_addon", "standalone_service"}:
            raise HTTPException(status_code=400, detail="install_mode_unsupported")
        requested_channel = str(body.channel or "stable").strip().lower() or "stable"
        local_install = bool(body.package_path and body.manifest and body.public_key_pem)
        catalog_install = bool(body.addon_id)
        if local_install and catalog_install:
            raise HTTPException(status_code=400, detail="install_mode_conflict")
        if not local_install and not catalog_install:
            raise HTTPException(status_code=400, detail="install_mode_missing")
        if local_install and requested_install_mode != "embedded_addon":
            raise HTTPException(status_code=400, detail="local_install_mode_unsupported")
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
        debug_catalog_addon_id: str | None = None
        debug_catalog_release_version: str | None = None
        debug_catalog_release_package_profile: str | None = None

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
            remediation_path: str | None = None,
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
                "remediation_path": remediation_path,
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
            expected_sha256_candidates: list[str] = []
            package_path: Path
            manifest: ReleaseManifest
            public_key_pem: str = ""
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
                normalized_manifest_checksum = _normalize_sha256(manifest.checksum)
                if normalized_manifest_checksum:
                    expected_sha256_candidates = [normalized_manifest_checksum]
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
                    channel=requested_channel,
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
                    debug_catalog_addon_id = str(
                        addon_item.get("id") or addon_item.get("addon_id") or body.addon_id or ""
                    ).strip() or None
                    debug_catalog_release_version = str(release_item.get("version") or "").strip() or None
                    debug_catalog_release_package_profile = _release_package_profile(addon_item, release_item)
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
                    debug_publisher_key_id = str(release_item.get("publisher_key_id") or "").strip() or None
                    release_signature_type = _release_signature_type(release_item)
                    debug_signature_type = release_signature_type

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
                            channel=requested_channel,
                        )
                        did_refresh_retry = True
                expected_sha256_candidates = _release_checksum_candidates(release_item, manifest.checksum)
                expected_sha256 = expected_sha256_candidates[0] if expected_sha256_candidates else ""
                debug_expected_sha256 = expected_sha256_candidates
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

            verify_release_artifact(manifest, artifact_bytes, public_key_pem)
            await audit_store.record(
                action="catalog_verify" if source_id != "local" else "install_verify",
                addon_id=manifest.id,
                version=manifest.version,
                status="success",
                message="verification_skipped",
                actor=actor,
            )

            resolve_manifest_compatibility(
                manifest,
                core_version=_configured_core_version(),
                installed_addons=installed_addons_with_versions(registry),
            )

            if requested_install_mode != manifest.package_profile:
                runtime_payload = _read_standalone_runtime(manifest.id, standalone_runtime)
                mismatch_payload: dict[str, Any] = {
                    "error": "catalog_package_profile_unsupported" if catalog_install else "package_profile_unsupported",
                    "mode": manifest.package_profile,
                    "package_profile": manifest.package_profile,
                    "requested_install_mode": requested_install_mode,
                    "runtime_path": runtime_payload.get("runtime_path"),
                    "runtime_state": runtime_payload.get("runtime_state"),
                    "registry_state": _registry_state_for_addon(registry, manifest.id),
                }
                if manifest.package_profile == "standalone_service":
                    service_dir = service_addon_dir(manifest.id, create=False)
                    staged_artifact_path = str(
                        _stage_standalone_artifact(
                            manifest.id,
                            manifest.version,
                            artifact_bytes,
                            expected_sha256_candidates,
                        )
                    )
                    standalone_dir = service_addon_dir(manifest.id, create=False)
                    mismatch_payload.update(
                        {
                            "supported_profiles": ["standalone_service"],
                            "remediation_path": "standalone_service_install",
                            "desired_path": _abs_path_str(standalone_dir / "desired.json"),
                            "runtime_path": _abs_path_str(runtime_payload.get("runtime_path")),
                            "staged_artifact_path": _abs_path_str(staged_artifact_path),
                            "service_dir": _abs_path_str(service_dir),
                            "hint": (
                                "release profile is standalone_service; retry install with "
                                "install_mode=standalone_service"
                            ),
                        }
                    )
                elif manifest.package_profile == "embedded_addon":
                    mismatch_payload.update(
                        {
                            "supported_profiles": ["embedded_addon"],
                            "remediation_path": "embedded_addon_install",
                            "hint": "release profile is embedded_addon; retry install with install_mode=embedded_addon",
                        }
                    )
                else:
                    mismatch_payload.update(
                        {
                            "supported_profiles": [manifest.package_profile],
                            "remediation_path": "install_mode_select",
                            "hint": "retry install with install_mode matching package_profile",
                        }
                    )
                if catalog_install:
                    mismatch_payload["source_id"] = debug_source_id
                    mismatch_payload["resolved_base_url"] = debug_resolved_base_url
                    mismatch_payload["artifact_url"] = debug_artifact_url
                raise HTTPException(status_code=400, detail=mismatch_payload)

            if manifest.package_profile == "standalone_service" and requested_install_mode == "standalone_service":
                staged_artifact_path = str(
                    _stage_standalone_artifact(
                        manifest.id,
                        manifest.version,
                        artifact_bytes,
                    )
                )
                service_dir = service_addon_dir(manifest.id, create=True)
                desired_path = service_dir / "desired.json"
                runtime_overrides = body.runtime_overrides if isinstance(body.runtime_overrides, dict) else {}
                manifest_runtime_defaults = _runtime_defaults_from_artifact(package_path, manifest.id) or manifest.runtime_defaults
                declared_groups = _docker_groups_from_artifact(package_path, manifest.id) or list(manifest.docker_groups or [])
                runtime_project_name = _compose_safe_project_name(
                    runtime_overrides.get("project_name") or f"synthia-addon-{manifest.id}",
                    manifest.id,
                )
                runtime_network = str(runtime_overrides.get("network") or "synthia_net").strip()
                if runtime_network.lower() in {"host", "host_network"}:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "standalone_runtime_network_unsupported",
                            "network": runtime_network,
                            "hint": "host networking is not allowed for standalone_service install runtime intent",
                        },
                    )
                if bool(runtime_overrides.get("privileged", False)):
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "standalone_runtime_privileged_unsupported",
                            "hint": "privileged runtime override is not allowed for standalone_service install runtime intent",
                        },
                    )
                runtime_ports = runtime_overrides.get("ports")
                if isinstance(runtime_ports, list):
                    runtime_ports_payload = [dict(item) for item in runtime_ports if isinstance(item, dict)]
                elif manifest_runtime_defaults is not None:
                    runtime_ports_payload = [item.model_dump(mode="python") for item in manifest_runtime_defaults.ports]
                else:
                    runtime_ports_payload = []
                if "bind_localhost" in runtime_overrides:
                    runtime_bind_localhost = bool(runtime_overrides.get("bind_localhost", True))
                elif manifest_runtime_defaults is not None:
                    runtime_bind_localhost = bool(manifest_runtime_defaults.bind_localhost)
                else:
                    runtime_bind_localhost = True
                raw_runtime_cpu = runtime_overrides.get("cpu")
                runtime_cpu: float | None = None
                if raw_runtime_cpu is not None and str(raw_runtime_cpu).strip() != "":
                    try:
                        runtime_cpu = float(str(raw_runtime_cpu).strip())
                    except Exception:
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "error": "standalone_runtime_cpu_invalid",
                                "cpu": raw_runtime_cpu,
                                "hint": "runtime_overrides.cpu must be a positive number",
                            },
                        )
                    if runtime_cpu <= 0:
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "error": "standalone_runtime_cpu_invalid",
                                "cpu": raw_runtime_cpu,
                                "hint": "runtime_overrides.cpu must be a positive number",
                            },
                        )
                raw_runtime_memory = runtime_overrides.get("memory")
                runtime_memory = None
                if raw_runtime_memory is not None:
                    normalized_memory = str(raw_runtime_memory).strip()
                    runtime_memory = normalized_memory or None
                raw_enabled_groups = (
                    body.enabled_docker_groups
                    if isinstance(body.enabled_docker_groups, list)
                    else runtime_overrides.get("enabled_docker_groups")
                )
                enabled_docker_groups = _normalize_enabled_docker_groups(raw_enabled_groups)
                _validate_requested_docker_groups(enabled_docker_groups, declared_groups)
                config_env_defaults: dict[str, str] = {
                    "CORE_URL": os.getenv("SYNTHIA_CORE_URL", "http://127.0.0.1:8000"),
                    "SYNTHIA_ADDON_ID": manifest.id,
                    "SYNTHIA_SERVICE_TOKEN": "${SYNTHIA_SERVICE_TOKEN}",
                }
                mqtt_host = os.getenv("MQTT_HOST")
                mqtt_port = os.getenv("MQTT_PORT")
                if mqtt_host:
                    config_env_defaults["MQTT_HOST"] = mqtt_host
                if mqtt_port:
                    config_env_defaults["MQTT_PORT"] = str(mqtt_port)
                config_env_overrides = body.config_env_overrides if isinstance(body.config_env_overrides, dict) else {}
                config_env = dict(config_env_defaults)
                for key, value in config_env_overrides.items():
                    config_env[str(key)] = str(value)
                desired_payload = build_desired_state(
                    addon_id=manifest.id,
                    catalog_id=source_id,
                    channel=requested_channel,
                    pinned_version=body.pinned_version or manifest.version,
                    artifact_url=source_release_url or "",
                    sha256=expected_sha256 or "",
                    publisher_key_id=debug_publisher_key_id or "",
                    signature_value=release_signature_b64 or "",
                    runtime_project_name=runtime_project_name,
                    runtime_network=runtime_network or "synthia_net",
                    runtime_ports=runtime_ports_payload,
                    runtime_bind_localhost=runtime_bind_localhost,
                    runtime_cpu=runtime_cpu,
                    runtime_memory=runtime_memory,
                    config_env=config_env,
                    desired_state=body.desired_state,
                    force_rebuild=body.force_rebuild,
                    enabled_docker_groups=enabled_docker_groups,
                )
                write_desired_state_atomic(desired_path, desired_payload)
                runtime_payload = _read_standalone_runtime(manifest.id, standalone_runtime)
                ui_redirect = _standalone_ui_redirect_info(manifest.id, runtime_payload)
                standalone_runtime_payload = runtime_payload.get("standalone_runtime")
                active_version = (
                    standalone_runtime_payload.get("active_version")
                    if isinstance(standalone_runtime_payload, dict)
                    else None
                )
                last_action = (
                    standalone_runtime_payload.get("last_action")
                    if isinstance(standalone_runtime_payload, dict)
                    else None
                )
                runtime_state = runtime_payload.get("runtime_state")
                supervisor_hint = None
                if runtime_state == "unknown":
                    supervisor_hint = "runtime.json not found yet; ensure synthia-supervisor is running"
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
                    message="standalone_install_desired_written",
                    actor=actor,
                )
                if events is not None:
                    await events.emit(
                        event_type="addon_installed",
                        source="store.api",
                        payload={
                            "addon_id": manifest.id,
                            "version": manifest.version,
                            "mode": manifest.package_profile,
                            "install_mode": requested_install_mode,
                            "runtime_state": runtime_state,
                        },
                    )
                return {
                    "ok": True,
                    "addon_id": manifest.id,
                    "mode": manifest.package_profile,
                    "requested_install_mode": requested_install_mode,
                    "channel": requested_channel,
                    "desired_state": body.desired_state,
                    "force_rebuild": bool(body.force_rebuild),
                    "enabled_docker_groups": enabled_docker_groups,
                    "desired_revision": desired_payload.get("desired_revision"),
                    "pinned_version": body.pinned_version or manifest.version,
                    "version": manifest.version,
                    "installed_path": None,
                    "enabled": registry.is_enabled(manifest.id),
                    "registry_loaded": manifest.id in registry.addons,
                    "hot_loaded": False,
                    "installed_from_source_id": source_id,
                    "installed_resolved_base_url": debug_resolved_base_url,
                    "installed_release_url": source_release_url,
                    "installed_sha256": expected_sha256,
                    "desired_path": _abs_path_str(desired_path),
                    "runtime_path": _abs_path_str(runtime_payload.get("runtime_path")),
                    "staged_artifact_path": _abs_path_str(staged_artifact_path),
                    "runtime_state": runtime_state,
                    "active_version": active_version,
                    "last_action": last_action,
                    "registry_state": _registry_state_for_addon(registry, manifest.id),
                    "service_dir": _abs_path_str(service_dir),
                    "supervisor_expected": True,
                    "supervisor_hint": supervisor_hint,
                    "ui_reachable": ui_redirect["ui_reachable"],
                    "ui_redirect_target": ui_redirect["ui_redirect_target"],
                    "ui_embed_target": ui_redirect["ui_embed_target"],
                    "ui_reason": ui_redirect["ui_reason"],
                    "next_steps": [
                        "Ensure synthia-supervisor is running and reconciling desired.json.",
                        "Check runtime.json and service logs if runtime_state stays unknown.",
                    ],
                    "security_guardrails": {
                        "bind_localhost": runtime_bind_localhost,
                        "privileged": False,
                        "network": runtime_network or "synthia_net",
                        "cpu": runtime_cpu,
                        "memory": runtime_memory,
                        "service_token_env_key": "SYNTHIA_SERVICE_TOKEN",
                    },
                    "remediation_path": None,
                    "standalone_runtime": standalone_runtime_payload,
                }

            if manifest.package_profile != "embedded_addon":
                staged_artifact_path: str | None = None
                if manifest.package_profile == "standalone_service":
                    staged_artifact_path = str(
                        _stage_standalone_artifact(
                            manifest.id,
                            manifest.version,
                            artifact_bytes,
                        )
                    )
                standalone_dir = service_addon_dir(manifest.id, create=False)
                desired_path = standalone_dir / "desired.json"
                runtime_payload = _read_standalone_runtime(manifest.id, standalone_runtime)
                error_payload: dict[str, Any] = {
                    "error": "catalog_package_profile_unsupported" if catalog_install else "package_profile_unsupported",
                    "mode": manifest.package_profile,
                    "package_profile": manifest.package_profile,
                    "supported_profiles": ["embedded_addon"],
                    "remediation_path": "standalone_deploy_register",
                    "desired_path": str(desired_path),
                    "runtime_path": runtime_payload.get("runtime_path"),
                    "runtime_state": runtime_payload.get("runtime_state"),
                    "registry_state": _registry_state_for_addon(registry, manifest.id),
                    "hint": (
                        "standalone_service packages are not installable as embedded addons; "
                        "deploy service package externally and register via /api/admin/addons/registry"
                    ),
                }
                if catalog_install:
                    error_payload["source_id"] = debug_source_id
                    error_payload["resolved_base_url"] = debug_resolved_base_url
                    error_payload["artifact_url"] = debug_artifact_url
                if staged_artifact_path:
                    error_payload["staged_artifact_path"] = staged_artifact_path
                raise HTTPException(status_code=400, detail=error_payload)

            result = _atomic_install_or_update(
                manifest=manifest,
                package_path=package_path,
                allow_replace=False,
            )

            if body.enable:
                registry.set_enabled(manifest.id, True)
            if mqtt_approval_service is not None:
                await mqtt_approval_service.reconcile(manifest.id)

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
            if events is not None:
                await events.emit(
                    event_type="addon_installed",
                    source="store.api",
                    payload={
                        "addon_id": manifest.id,
                        "version": manifest.version,
                        "mode": manifest.package_profile,
                        "install_mode": requested_install_mode,
                    },
                )
            return {
                "ok": True,
                "addon_id": manifest.id,
                "mode": manifest.package_profile,
                "requested_install_mode": requested_install_mode,
                "channel": requested_channel,
                "desired_state": body.desired_state,
                "pinned_version": body.pinned_version,
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
                "desired_path": None,
                "runtime_path": None,
                "staged_artifact_path": None,
                "runtime_state": None,
                "registry_state": _registry_state_for_addon(registry, manifest.id),
                "service_dir": None,
                "supervisor_expected": False,
                "next_steps": [],
                "remediation_path": None,
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
        except SSAPDesiredValidationError as exc:
            _persist_last_install_error(error_code=SSAPDesiredValidationError.code)
            await audit_store.record(
                action="install",
                addon_id=(body.manifest.id if body.manifest is not None else (body.addon_id or "__unknown__")),
                version=(body.manifest.version if body.manifest is not None else body.version),
                status="failed",
                message=SSAPDesiredValidationError.code,
                actor=actor,
            )
            raise HTTPException(status_code=400, detail=str(exc))
        except HTTPException as exc:
            detail_source_id: str | None = None
            detail_artifact_url: str | None = None
            detail_expected_sha256: list[str] | None = None
            detail_actual_sha256: str | None = None
            detail_remediation_path: str | None = None
            error_code: str | None = None
            detail_payload = exc.detail
            if isinstance(detail_payload, dict):
                error_code = str(detail_payload.get("error") or detail_payload.get("code") or "").strip() or None
                detail_source_id = str(detail_payload.get("source_id") or "").strip() or None
                detail_artifact_url = str(detail_payload.get("artifact_url") or "").strip() or None
                detail_actual_sha256 = str(detail_payload.get("actual_sha256") or "").strip() or None
                detail_remediation_path = str(detail_payload.get("remediation_path") or "").strip() or None
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
                remediation_path=detail_remediation_path,
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
            if catalog_install and "version must be valid semver" in detail:
                payload = {
                    "error": "catalog_release_version_invalid",
                    "source_id": debug_source_id,
                    "resolved_base_url": debug_resolved_base_url,
                    "artifact_url": debug_artifact_url,
                    "catalog_addon_id": debug_catalog_addon_id,
                    "catalog_release_version": debug_catalog_release_version,
                    "remediation_path": "catalog_release_version_format",
                    "hint": (
                        "catalog release version must be semver or semver+suffix "
                        "(for example 1.2.3 or 1.2.3d)"
                    ),
                }
                _persist_last_install_error(
                    error_code="catalog_release_version_invalid",
                    source_id=debug_source_id,
                    artifact_url=debug_artifact_url,
                    remediation_path="catalog_release_version_format",
                )
                raise HTTPException(status_code=400, detail=payload)
            if detail == "addon_already_installed":
                raise HTTPException(status_code=409, detail=detail)
            if catalog_install and detail.startswith("missing_backend_entrypoint"):
                layout_hint = None
                if detail == "missing_backend_entrypoint:service_layout_app_main":
                    layout_hint = "service_layout_app_main"
                if layout_hint == "service_layout_app_main":
                    if debug_catalog_release_package_profile == "embedded_addon":
                        mismatch_payload: dict[str, Any] = {
                            "error": "catalog_profile_layout_mismatch",
                            "reason": "embedded_profile_with_service_layout",
                            "source_id": debug_source_id,
                            "resolved_base_url": debug_resolved_base_url,
                            "artifact_url": debug_artifact_url,
                            "layout_hint": layout_hint,
                            "expected_package_profile": "embedded_addon",
                            "detected_package_profile": "standalone_service",
                            "remediation_path": "embedded_repackage",
                            "hint": (
                                "catalog release metadata indicates embedded_addon but artifact layout matches "
                                "standalone_service (app/main.py); publish an embedded artifact with "
                                "backend/addon.py or change release profile to standalone_service"
                            ),
                        }
                        if debug_catalog_addon_id:
                            mismatch_payload["catalog_addon_id"] = debug_catalog_addon_id
                        if debug_catalog_release_version:
                            mismatch_payload["catalog_release_version"] = debug_catalog_release_version
                        mismatch_payload["catalog_release_package_profile"] = "embedded_addon"
                        _persist_last_install_error(
                            error_code="catalog_profile_layout_mismatch",
                            remediation_path="embedded_repackage",
                        )
                        raise HTTPException(status_code=409, detail=mismatch_payload)
                    unsupported_payload: dict[str, Any] = {
                        "error": "catalog_package_profile_unsupported",
                        "package_profile": "standalone_service",
                        "supported_profiles": ["embedded_addon"],
                        "source_id": debug_source_id,
                        "resolved_base_url": debug_resolved_base_url,
                        "artifact_url": debug_artifact_url,
                        "layout_hint": layout_hint,
                        "remediation_path": "standalone_deploy_register",
                        "hint": (
                            "artifact appears to be a standalone service package (app/main.py); "
                            "set package_profile=standalone_service and deploy/register externally, "
                            "or ship embedded_addon layout with backend/addon.py"
                        ),
                    }
                    if debug_catalog_addon_id:
                        unsupported_payload["catalog_addon_id"] = debug_catalog_addon_id
                    if debug_catalog_release_version:
                        unsupported_payload["catalog_release_version"] = debug_catalog_release_version
                    if debug_catalog_release_package_profile:
                        unsupported_payload["catalog_release_package_profile"] = debug_catalog_release_package_profile
                    _persist_last_install_error(
                        error_code="catalog_package_profile_unsupported",
                        remediation_path="standalone_deploy_register",
                    )
                    raise HTTPException(status_code=400, detail=unsupported_payload)
                error_payload: dict[str, Any] = {
                    "error": "catalog_package_layout_invalid",
                    "reason": "missing_backend_entrypoint",
                    "source_id": debug_source_id,
                    "resolved_base_url": debug_resolved_base_url,
                    "artifact_url": debug_artifact_url,
                    "expected_package_profile": debug_package_profile or "embedded_addon",
                    "expected_backend_entrypoint": "backend/addon.py",
                }
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
            if mqtt_approval_service is not None:
                await mqtt_approval_service.reconcile(body.manifest.id)

            await audit_store.record(
                action="update",
                addon_id=body.manifest.id,
                version=body.manifest.version,
                status="success",
                message="update_completed",
                actor=actor,
            )
            if events is not None:
                await events.emit(
                    event_type="addon_updated",
                    source="store.api",
                    payload={
                        "addon_id": body.manifest.id,
                        "version": body.manifest.version,
                        "mode": body.manifest.package_profile,
                    },
                )
            return {
                "ok": True,
                "addon_id": body.manifest.id,
                "mode": body.manifest.package_profile,
                "version": body.manifest.version,
                "installed_path": str(result.addon_dir),
                "enabled": registry.is_enabled(body.manifest.id),
                "registry_loaded": body.manifest.id in registry.addons,
                # TODO(phase3): report true hot-reload runtime status once dynamic module reload is supported.
                "hot_loaded": False,
                "desired_path": None,
                "runtime_path": None,
                "staged_artifact_path": None,
                "runtime_state": None,
                "registry_state": _registry_state_for_addon(registry, body.manifest.id),
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

    @router.post("/standalone/update")
    async def update_standalone_desired(
        body: StoreStandaloneUpdateRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        addon_id = body.addon_id.strip()
        actor = body.actor or "admin_token"
        service_dir = service_addon_dir(addon_id, create=False)
        desired_path = service_dir / "desired.json"
        if not service_dir.exists() or not desired_path.exists():
            raise HTTPException(status_code=404, detail="standalone_service_not_installed")

        current_desired = _load_json_file(desired_path)
        if not isinstance(current_desired, dict):
            raise HTTPException(status_code=400, detail="desired_missing_or_invalid")

        install_source = current_desired.get("install_source")
        install_source = install_source if isinstance(install_source, dict) else {}
        release = install_source.get("release")
        release = release if isinstance(release, dict) else {}
        runtime_current = current_desired.get("runtime")
        runtime_current = runtime_current if isinstance(runtime_current, dict) else {}
        config_current = current_desired.get("config")
        config_current = config_current if isinstance(config_current, dict) else {}
        config_env_current = config_current.get("env")
        config_env_current = config_env_current if isinstance(config_env_current, dict) else {}
        runtime_overrides = body.runtime_overrides if isinstance(body.runtime_overrides, dict) else {}

        runtime_project_name = _compose_safe_project_name(
            runtime_overrides.get("project_name") or runtime_current.get("project_name") or f"synthia-addon-{addon_id}",
            addon_id,
        )
        runtime_network = str(runtime_overrides.get("network") or runtime_current.get("network") or "synthia_net").strip()
        if runtime_network.lower() in {"host", "host_network"}:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "standalone_runtime_network_unsupported",
                    "network": runtime_network,
                    "hint": "host networking is not allowed for standalone_service runtime intent",
                },
            )
        if bool(runtime_overrides.get("privileged", False)):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "standalone_runtime_privileged_unsupported",
                    "hint": "privileged runtime override is not allowed for standalone_service runtime intent",
                },
            )

        runtime_ports = runtime_overrides.get("ports")
        if isinstance(runtime_ports, list):
            runtime_ports_payload = [dict(item) for item in runtime_ports if isinstance(item, dict)]
        elif isinstance(runtime_current.get("ports"), list):
            runtime_ports_payload = [dict(item) for item in runtime_current.get("ports") if isinstance(item, dict)]
        else:
            runtime_ports_payload = []

        if "bind_localhost" in runtime_overrides:
            runtime_bind_localhost = bool(runtime_overrides.get("bind_localhost", True))
        else:
            runtime_bind_localhost = bool(runtime_current.get("bind_localhost", True))

        raw_runtime_cpu = runtime_overrides.get("cpu", runtime_current.get("cpu"))
        runtime_cpu: float | None = None
        if raw_runtime_cpu is not None and str(raw_runtime_cpu).strip() != "":
            try:
                runtime_cpu = float(str(raw_runtime_cpu).strip())
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "standalone_runtime_cpu_invalid",
                        "cpu": raw_runtime_cpu,
                        "hint": "runtime_overrides.cpu must be a positive number",
                    },
                )
            if runtime_cpu <= 0:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "standalone_runtime_cpu_invalid",
                        "cpu": raw_runtime_cpu,
                        "hint": "runtime_overrides.cpu must be a positive number",
                    },
                )
        raw_runtime_memory = runtime_overrides.get("memory", runtime_current.get("memory"))
        runtime_memory = None
        if raw_runtime_memory is not None:
            normalized_memory = str(raw_runtime_memory).strip()
            runtime_memory = normalized_memory or None

        config_env = {str(key): str(value) for key, value in config_env_current.items()}
        config_env_overrides = body.config_env_overrides if isinstance(body.config_env_overrides, dict) else {}
        for key, value in config_env_overrides.items():
            config_env[str(key)] = str(value)

        install_state = _get_install_state(addon_id) or {}
        catalog_id = (
            (body.source_id.strip() if isinstance(body.source_id, str) and body.source_id.strip() else None)
            or str(install_source.get("catalog_id") or "").strip()
            or str(install_state.get("installed_from_source_id") or "").strip()
            or "official"
        )
        channel = (str(body.channel or current_desired.get("channel") or "stable").strip().lower() or "stable")
        desired_state = str(body.desired_state or current_desired.get("desired_state") or "running").strip().lower() or "running"
        pinned_version = (
            str(body.pinned_version).strip()
            if isinstance(body.pinned_version, str) and body.pinned_version.strip()
            else (
                str(current_desired.get("pinned_version")).strip()
                if current_desired.get("pinned_version") is not None
                else None
            )
        )
        declared_groups = _docker_groups_from_service(addon_id, pinned_version) or []
        raw_enabled_groups = (
            body.enabled_docker_groups
            if isinstance(body.enabled_docker_groups, list)
            else (
                runtime_overrides.get("enabled_docker_groups")
                if isinstance(runtime_overrides.get("enabled_docker_groups"), list)
                else current_desired.get("enabled_docker_groups")
            )
        )
        enabled_docker_groups = _normalize_enabled_docker_groups(raw_enabled_groups)
        _validate_requested_docker_groups(enabled_docker_groups, declared_groups)

        # Rewriting desired intent for an already-installed standalone addon must trigger
        # supervisor rebuild/recreate so compose/runtime changes are not skipped.
        desired_payload = build_desired_state(
            addon_id=addon_id,
            catalog_id=catalog_id,
            channel=channel,
            pinned_version=pinned_version,
            artifact_url=str(release.get("artifact_url") or "").strip(),
            sha256=str(release.get("sha256") or "").strip(),
            publisher_key_id=str(release.get("publisher_key_id") or "").strip(),
            signature_value=str((release.get("signature") or {}).get("value") if isinstance(release.get("signature"), dict) else ""),
            runtime_project_name=runtime_project_name,
            runtime_network=runtime_network or "synthia_net",
            runtime_ports=runtime_ports_payload,
            runtime_bind_localhost=runtime_bind_localhost,
            runtime_cpu=runtime_cpu,
            runtime_memory=runtime_memory,
            config_env=config_env,
            desired_state=desired_state,
            force_rebuild=True,
            enabled_docker_groups=enabled_docker_groups,
        )
        write_desired_state_atomic(desired_path, desired_payload)
        runtime_payload = _read_standalone_runtime(addon_id, standalone_runtime)
        ui_redirect = _standalone_ui_redirect_info(addon_id, runtime_payload)

        await audit_store.record(
            action="standalone_update",
            addon_id=addon_id,
            version=pinned_version,
            status="success",
            message="standalone_desired_updated",
            actor=actor,
        )
        return {
            "ok": True,
            "addon_id": addon_id,
            "desired_path": _abs_path_str(desired_path),
            "runtime_path": _abs_path_str(runtime_payload.get("runtime_path")),
            "runtime_state": runtime_payload.get("runtime_state"),
            "standalone_runtime": runtime_payload.get("standalone_runtime"),
            "ui_reachable": ui_redirect["ui_reachable"],
            "ui_redirect_target": ui_redirect["ui_redirect_target"],
            "ui_embed_target": ui_redirect["ui_embed_target"],
            "ui_reason": ui_redirect["ui_reason"],
            "desired_state": desired_state,
            "pinned_version": pinned_version,
            "force_rebuild": True,
            "enabled_docker_groups": enabled_docker_groups,
            "desired_revision": desired_payload.get("desired_revision"),
        }

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

            embedded_installed = (_addons_root() / addon_id).exists()
            standalone_installed = service_addon_dir(addon_id, create=False).exists()
            if not embedded_installed and not standalone_installed:
                raise RuntimeError("addon_not_installed")

            if embedded_installed:
                atomic_uninstall(addon_id)
            standalone_uninstall = _uninstall_standalone_service(addon_id) if standalone_installed else {"removed": False}
            registry.set_enabled(addon_id, False)
            deleted_registered = registry.delete_registered(addon_id)
            if mqtt_approval_service is not None:
                await mqtt_approval_service.revoke_or_mark(addon_id, reason="addon_uninstalled")
            _clear_install_state(addon_id)
            compose_down_error = standalone_uninstall.get("compose_down_error")
            audit_message = "uninstall_completed"
            if compose_down_error:
                audit_message = "uninstall_completed_with_compose_down_warning"
            await audit_store.record(
                action="uninstall",
                addon_id=addon_id,
                version=version,
                status="success",
                message=audit_message,
                actor=actor,
            )
            return {
                "ok": True,
                "addon_id": addon_id,
                "enabled": registry.is_enabled(addon_id),
                "embedded_removed": embedded_installed,
                "standalone_removed": bool(standalone_uninstall.get("removed")),
                "registered_deleted": deleted_registered,
                "standalone_compose_file": standalone_uninstall.get("compose_file"),
                "standalone_project_name": standalone_uninstall.get("project_name"),
                "standalone_compose_down_error": compose_down_error,
                "standalone_removed_image_ids": standalone_uninstall.get("removed_image_ids"),
                "standalone_image_remove_error": standalone_uninstall.get("image_remove_error"),
            }
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

    @router.get("/status/summary")
    async def addon_store_status_summary():
        return _install_error_summary()

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
        runtime_payload = _read_standalone_runtime(addon_id, standalone_runtime)
        ui_redirect = _standalone_ui_redirect_info(addon_id, runtime_payload)

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
            "runtime_path": runtime_payload.get("runtime_path"),
            "runtime_state": runtime_payload.get("runtime_state"),
            "standalone_runtime": runtime_payload.get("standalone_runtime"),
            "runtime_error": runtime_payload.get("runtime_error"),
            "ui_reachable": ui_redirect["ui_reachable"],
            "ui_redirect_target": ui_redirect["ui_redirect_target"],
            "ui_embed_target": ui_redirect["ui_embed_target"],
            "ui_reason": ui_redirect["ui_reason"],
        }

    @router.get("/status/{addon_id}/diagnostics")
    async def addon_store_status_diagnostics(addon_id: str):
        runtime_payload = _read_standalone_runtime(addon_id, standalone_runtime)
        return {
            "ok": True,
            "addon_id": addon_id,
            "runtime_path": runtime_payload.get("runtime_path"),
            "runtime_state": runtime_payload.get("runtime_state"),
            "runtime_error": runtime_payload.get("runtime_error"),
            "last_error_summary": _runtime_error_summary(runtime_payload),
            "standalone_runtime": runtime_payload.get("standalone_runtime"),
            "retention": _standalone_retention_diagnostics(addon_id, runtime_payload),
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

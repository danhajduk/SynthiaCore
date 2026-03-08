
from __future__ import annotations
import hashlib
import json, os, time, logging, shutil
from pathlib import Path
from typing import Dict, Any
from .models import DesiredState, RuntimeState, ReconcileResult
from .docker_compose import compose_up, compose_down, ensure_extracted, ensure_compose_files

DEFAULT_INTERVAL_S = 5
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_KEEP_VERSIONS = 3
MIN_KEEP_VERSIONS = 2
log = logging.getLogger("synthia.supervisor")


def configure_logging() -> None:
    level_name = os.environ.get("SYNTHIA_SUPERVISOR_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper() or DEFAULT_LOG_LEVEL
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

def load_json(path: Path) -> Dict[str, Any]:
    log.info("load_json path=%s", path)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)
    log.info("write_json path=%s", path)


def activate_current_symlink(addon_dir: Path, version_dir: Path) -> None:
    current = addon_dir / "current"
    next_link = addon_dir / ".current.next"
    if next_link.exists() or next_link.is_symlink():
        next_link.unlink()
    next_link.symlink_to(version_dir)
    # Atomic replace: current now points to the newly-started version
    next_link.replace(current)


def resolve_current_version(addon_dir: Path) -> str | None:
    current = addon_dir / "current"
    if not current.is_symlink():
        return None
    try:
        target = current.resolve()
    except OSError:
        return None
    if target.parent.name != "versions":
        return None
    return target.name


def _retention_keep_versions() -> int:
    raw = os.environ.get("SYNTHIA_SUPERVISOR_KEEP_VERSIONS", "").strip()
    if not raw:
        return DEFAULT_KEEP_VERSIONS
    try:
        parsed = int(raw)
    except Exception:
        return DEFAULT_KEEP_VERSIONS
    return max(parsed, MIN_KEEP_VERSIONS)


def _version_entries(addon_dir: Path) -> list[tuple[str, Path, float]]:
    versions_root = addon_dir / "versions"
    if not versions_root.exists():
        return []
    out: list[tuple[str, Path, float]] = []
    for entry in versions_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            mtime = entry.stat().st_mtime
        except Exception:
            mtime = 0.0
        out.append((entry.name, entry, mtime))
    out.sort(key=lambda item: item[2], reverse=True)
    return out


def _cleanup_old_versions(addon_dir: Path, *, active_version: str | None, previous_version: str | None) -> dict[str, Any]:
    keep_versions = _retention_keep_versions()
    entries = _version_entries(addon_dir)
    keep_set: set[str] = set()
    if active_version:
        keep_set.add(active_version)
    if previous_version:
        keep_set.add(previous_version)
    for name, _path, _mtime in entries:
        if len(keep_set) >= keep_versions:
            break
        keep_set.add(name)

    pruned: list[str] = []
    for name, path, _mtime in entries:
        if name in keep_set:
            continue
        shutil.rmtree(path, ignore_errors=True)
        pruned.append(name)

    return {
        "keep_versions": keep_versions,
        "active_version": active_version,
        "previous_version": previous_version,
        "retained_versions": sorted(keep_set),
        "pruned_versions": sorted(pruned),
    }

def _safe_load_runtime_state(runtime_path: Path) -> RuntimeState | None:
    if not runtime_path.exists():
        return None
    try:
        raw = load_json(runtime_path)
        return RuntimeState(**raw)
    except Exception:
        return None


def _compose_input_digest(desired: DesiredState) -> str:
    runtime = desired.runtime
    payload = {
        "addon_id": desired.addon_id,
        "network": runtime.network or "synthia_net",
        "bind_localhost": bool(getattr(runtime, "bind_localhost", True)),
        "ports": list(getattr(runtime, "ports", []) or []),
        "cpu": getattr(runtime, "cpu", None),
        "memory": getattr(runtime, "memory", None),
        "enabled_docker_groups": sorted(
            {str(item).strip() for item in list(getattr(desired, "enabled_docker_groups", []) or []) if str(item).strip()}
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _build_reconcile_result(
    *,
    desired: DesiredState,
    runtime: RuntimeState,
    prior_runtime: RuntimeState | None,
) -> ReconcileResult:
    prior_state = prior_runtime.state if prior_runtime is not None else "unknown"
    state_transition = f"{prior_state}->{runtime.state}"
    changed = (
        prior_runtime is None
        or prior_runtime.state != runtime.state
        or prior_runtime.active_version != runtime.active_version
        or prior_runtime.previous_version != runtime.previous_version
    )
    return ReconcileResult(
        addon_id=runtime.addon_id,
        desired_state=desired.desired_state,
        final_state=runtime.state,
        active_version=runtime.active_version,
        previous_version=runtime.previous_version,
        changed=changed,
        state_transition=state_transition,
        error=runtime.error or runtime.last_error,
        compose_project_name=desired.runtime.project_name,
    )


def _emit_lifecycle_event(result: ReconcileResult) -> dict[str, Any] | None:
    if result.final_state == "error":
        payload = {
            "event_type": "addon_failed",
            "addon_id": result.addon_id,
            "desired_state": result.desired_state,
            "final_state": result.final_state,
            "state_transition": result.state_transition,
            "active_version": result.active_version,
            "previous_version": result.previous_version,
            "compose_project_name": result.compose_project_name,
            "error": result.error,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        log.info("post_reconcile_event addon_id=%s event=%s payload=%s", result.addon_id, payload["event_type"], payload)
        return payload
    if not result.changed:
        return None
    if result.final_state == "running" and result.active_version:
        event_type = "addon_updated" if result.previous_version and result.previous_version != result.active_version else "addon_started"
        payload = {
            "event_type": event_type,
            "addon_id": result.addon_id,
            "desired_state": result.desired_state,
            "final_state": result.final_state,
            "state_transition": result.state_transition,
            "active_version": result.active_version,
            "previous_version": result.previous_version,
            "compose_project_name": result.compose_project_name,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        log.info("post_reconcile_event addon_id=%s event=%s payload=%s", result.addon_id, payload["event_type"], payload)
        return payload
    return None


def run_post_reconcile_hooks(addon_dir: Path, result: ReconcileResult) -> dict[str, Any]:
    hooks = {
        "cleanup": None,
        "lifecycle_event": None,
    }
    if result.final_state == "running" and not result.error:
        cleanup_result = _cleanup_old_versions(
            addon_dir,
            active_version=result.active_version,
            previous_version=result.previous_version,
        )
        hooks["cleanup"] = cleanup_result
    hooks["lifecycle_event"] = _emit_lifecycle_event(result)
    return hooks


def reconcile_one(addon_dir: Path) -> ReconcileResult | None:
    desired_path = addon_dir / "desired.json"
    runtime_path = addon_dir / "runtime.json"
    if not desired_path.exists():
        log.debug("reconcile_skip addon_dir=%s reason=missing_desired", addon_dir)
        return None
    log.info("reconcile_start addon_dir=%s", addon_dir)
    desired = DesiredState(**load_json(desired_path))
    prior_runtime = _safe_load_runtime_state(runtime_path)
    rt = RuntimeState.new(desired.addon_id)
    previous_version = resolve_current_version(addon_dir)
    log.info(
        "desired_loaded addon_id=%s desired_state=%s pinned_version=%s previous_version=%s",
        desired.addon_id,
        desired.desired_state,
        desired.pinned_version,
        previous_version,
    )

    try:
        requested_groups = sorted(
            {
                str(item).strip()
                for item in list(getattr(desired, "enabled_docker_groups", []) or [])
                if str(item).strip()
            }
        )
        if desired.desired_state == "stopped":
            compose_file = addon_dir / "current" / "docker-compose.yml"
            compose_files_in_use = []
            if prior_runtime is not None and list(prior_runtime.compose_files_in_use or []):
                compose_files_in_use = [
                    Path(p)
                    for p in list(prior_runtime.compose_files_in_use)
                    if isinstance(p, str) and p.strip()
                ]
            elif compose_file.exists():
                compose_files_in_use = [compose_file]
            log.info(
                "desired_state_stopped addon_id=%s compose_files=%s",
                desired.addon_id,
                [str(item) for item in compose_files_in_use],
            )
            if compose_files_in_use:
                compose_down(compose_files_in_use, desired.runtime.project_name)
            rt.state = "stopped"
            rt.last_applied_desired_revision = desired.desired_revision
            rt.requested_docker_groups = requested_groups
            rt.active_docker_groups = []
            rt.failed_docker_groups = []
            rt.compose_files_in_use = [str(item) for item in compose_files_in_use]
            if desired.force_rebuild and desired.desired_revision:
                rt.last_force_rebuild_revision = desired.desired_revision
            write_json_atomic(runtime_path, rt.model_dump())
            log.info("reconcile_done addon_id=%s state=stopped", desired.addon_id)
            return _build_reconcile_result(desired=desired, runtime=rt, prior_runtime=prior_runtime)

        version = desired.pinned_version or "latest"
        desired_revision = str(desired.desired_revision or "").strip() or None
        force_rebuild = bool(getattr(desired, "force_rebuild", False))
        force_rebuild_already_applied = bool(
            force_rebuild
            and desired_revision is not None
            and prior_runtime is not None
            and prior_runtime.last_force_rebuild_revision == desired_revision
        )
        compose_digest = _compose_input_digest(desired)
        if (
            prior_runtime is not None
            and prior_runtime.state == "running"
            and prior_runtime.active_version == version
            and desired_revision is not None
            and prior_runtime.last_applied_desired_revision == desired_revision
            and not force_rebuild
        ):
            log.info(
                "reconcile_noop addon_id=%s version=%s desired_revision=%s",
                desired.addon_id,
                version,
                desired_revision,
            )
            return _build_reconcile_result(desired=desired, runtime=prior_runtime, prior_runtime=prior_runtime)
        if (
            prior_runtime is not None
            and prior_runtime.state == "running"
            and prior_runtime.active_version == version
            and desired_revision is not None
            and prior_runtime.last_applied_desired_revision == desired_revision
            and force_rebuild_already_applied
        ):
            log.info(
                "reconcile_noop addon_id=%s version=%s desired_revision=%s reason=force_rebuild_already_applied",
                desired.addon_id,
                version,
                desired_revision,
            )
            return _build_reconcile_result(desired=desired, runtime=prior_runtime, prior_runtime=prior_runtime)
        version_dir = addon_dir / "versions" / version
        version_dir.mkdir(parents=True, exist_ok=True)

        artifact_path = version_dir / "addon.tgz"
        extracted_dir = version_dir / "extracted"
        compose_file = version_dir / "docker-compose.yml"
        env_file = version_dir / "runtime.env"

        if not artifact_path.exists():
            log.error("artifact_missing addon_id=%s artifact=%s", desired.addon_id, artifact_path)
            raise RuntimeError("Artifact missing")

        log.info("verify_skipped addon_id=%s reason=signature_checks_disabled", desired.addon_id)
        ensure_extracted(artifact_path, extracted_dir)

        active_groups: list[str] = []
        failed_groups: list[str] = []
        compose_files = [compose_file]
        for group in requested_groups:
            group_compose = extracted_dir / f"docker-compose.group-{group}.yml"
            if group_compose.exists():
                compose_files.append(group_compose)
                active_groups.append(group)
            else:
                failed_groups.append(group)

        if compose_file.exists() and force_rebuild and not force_rebuild_already_applied:
            compose_file.unlink()
            log.info(
                "compose_file_regen addon_id=%s version=%s reason=force_rebuild",
                desired.addon_id,
                version,
            )
        elif (
            compose_file.exists()
            and prior_runtime is not None
            and prior_runtime.active_version == version
            and prior_runtime.last_applied_compose_digest is not None
            and prior_runtime.last_applied_compose_digest != compose_digest
        ):
            compose_file.unlink()
            log.info(
                "compose_file_regen addon_id=%s version=%s reason=compose_digest_changed old=%s new=%s",
                desired.addon_id,
                version,
                prior_runtime.last_applied_compose_digest,
                compose_digest,
            )
        ensure_compose_files(desired, extracted_dir, compose_file, env_file)

        compose_up(
            compose_files,
            desired.runtime.project_name,
            force_rebuild=(force_rebuild and not force_rebuild_already_applied),
        )
        activate_current_symlink(addon_dir, version_dir)

        rt.state = "running"
        rt.active_version = version
        rt.previous_version = previous_version
        rt.rollback_available = bool(previous_version and previous_version != version)
        rt.last_error = None
        rt.last_applied_desired_revision = desired_revision
        rt.last_applied_compose_digest = compose_digest
        rt.requested_docker_groups = requested_groups
        rt.active_docker_groups = active_groups
        rt.failed_docker_groups = failed_groups
        rt.compose_files_in_use = [str(item) for item in compose_files]
        if force_rebuild and desired_revision:
            rt.last_force_rebuild_revision = desired_revision
        log.info(
            "reconcile_done addon_id=%s state=running active_version=%s rollback_available=%s",
            desired.addon_id,
            rt.active_version,
            rt.rollback_available,
        )

    except Exception as e:
        rt.state = "error"
        message = str(e)
        rt.error = message
        rt.last_error = message
        rt.previous_version = previous_version
        rt.rollback_available = bool(previous_version)
        log.exception("reconcile_error addon_id=%s error=%s", rt.addon_id, message)

    write_json_atomic(runtime_path, rt.model_dump())
    return _build_reconcile_result(desired=desired, runtime=rt, prior_runtime=prior_runtime)

def main():
    configure_logging()
    addons_dir = Path(os.environ.get("SYNTHIA_ADDONS_DIR", "../SynthiaAddons")).resolve()
    services_dir = addons_dir / "services"
    services_dir.mkdir(parents=True, exist_ok=True)
    interval = int(os.environ.get("SYNTHIA_SUPERVISOR_INTERVAL_S", DEFAULT_INTERVAL_S))
    log.info("supervisor_start services_dir=%s interval_s=%s", services_dir, interval)

    while True:
        for addon_dir in services_dir.iterdir():
            if addon_dir.is_dir():
                result = reconcile_one(addon_dir)
                if result is None:
                    continue
                hook_result = run_post_reconcile_hooks(addon_dir, result)
                cleanup = hook_result.get("cleanup")
                if isinstance(cleanup, dict):
                    log.info(
                        "post_reconcile_cleanup addon_id=%s retained_versions=%s pruned_versions=%s",
                        result.addon_id,
                        cleanup.get("retained_versions"),
                        cleanup.get("pruned_versions"),
                    )
        time.sleep(interval)

if __name__ == "__main__":
    main()

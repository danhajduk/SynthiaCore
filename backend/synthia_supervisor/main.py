
from __future__ import annotations
import json, os, time, logging
from pathlib import Path
from typing import Dict, Any
from .models import DesiredState, RuntimeState
from .docker_compose import compose_up, compose_down, ensure_extracted, ensure_compose_files

DEFAULT_INTERVAL_S = 5
DEFAULT_LOG_LEVEL = "INFO"
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

def reconcile_one(addon_dir: Path):
    desired_path = addon_dir / "desired.json"
    runtime_path = addon_dir / "runtime.json"
    if not desired_path.exists():
        log.debug("reconcile_skip addon_dir=%s reason=missing_desired", addon_dir)
        return
    log.info("reconcile_start addon_dir=%s", addon_dir)
    desired = DesiredState(**load_json(desired_path))
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
        if desired.desired_state == "stopped":
            compose_file = addon_dir / "current" / "docker-compose.yml"
            log.info("desired_state_stopped addon_id=%s compose_file=%s", desired.addon_id, compose_file)
            if compose_file.exists():
                compose_down(compose_file, desired.runtime.project_name)
            rt.state = "stopped"
            write_json_atomic(runtime_path, rt.model_dump())
            log.info("reconcile_done addon_id=%s state=stopped", desired.addon_id)
            return

        version = desired.pinned_version or "latest"
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
        ensure_compose_files(desired, extracted_dir, compose_file, env_file)

        compose_up(compose_file, desired.runtime.project_name)
        activate_current_symlink(addon_dir, version_dir)

        rt.state = "running"
        rt.active_version = version
        rt.previous_version = previous_version
        rt.rollback_available = bool(previous_version and previous_version != version)
        rt.last_error = None
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
                reconcile_one(addon_dir)
        time.sleep(interval)

if __name__ == "__main__":
    main()

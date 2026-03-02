
from __future__ import annotations
import json, os, time
from pathlib import Path
from typing import Dict, Any
from .models import DesiredState, RuntimeState
from .crypto import verify_release_option_a
from .docker_compose import compose_up, compose_down, ensure_extracted, ensure_compose_files

DEFAULT_INTERVAL_S = 5

def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)

def reconcile_one(addon_dir: Path):
    desired_path = addon_dir / "desired.json"
    runtime_path = addon_dir / "runtime.json"
    if not desired_path.exists():
        return
    desired = DesiredState(**load_json(desired_path))
    rt = RuntimeState.new(desired.addon_id)

    try:
        if desired.desired_state == "stopped":
            compose_file = addon_dir / "current" / "docker-compose.yml"
            if compose_file.exists():
                compose_down(compose_file, desired.runtime.project_name)
            rt.state = "stopped"
            write_json_atomic(runtime_path, rt.dict())
            return

        version = desired.pinned_version or "latest"
        version_dir = addon_dir / "versions" / version
        version_dir.mkdir(parents=True, exist_ok=True)

        artifact_path = version_dir / "addon.tgz"
        extracted_dir = version_dir / "extracted"
        compose_file = version_dir / "docker-compose.yml"
        env_file = version_dir / "runtime.env"

        if not artifact_path.exists():
            raise RuntimeError("Artifact missing")

        verify_release_option_a(
            artifact_path,
            desired.install_source["release"]["sha256"],
            desired.install_source["release"]["signature"]["value"],
            desired.install_source["release"]["publisher_key_id"],
        )
        ensure_extracted(artifact_path, extracted_dir)
        ensure_compose_files(desired, extracted_dir, compose_file, env_file)

        current = addon_dir / "current"
        if current.exists() or current.is_symlink():
            current.unlink()
        current.symlink_to(version_dir)

        compose_up(compose_file, desired.runtime.project_name)

        rt.state = "running"
        rt.active_version = version

    except Exception as e:
        rt.state = "error"
        rt.error = str(e)

    write_json_atomic(runtime_path, rt.dict())

def main():
    addons_dir = Path(os.environ.get("SYNTHIA_ADDONS_DIR", "../SynthiaAddons")).resolve()
    services_dir = addons_dir / "services"
    services_dir.mkdir(parents=True, exist_ok=True)
    interval = int(os.environ.get("SYNTHIA_SUPERVISOR_INTERVAL_S", DEFAULT_INTERVAL_S))

    while True:
        for addon_dir in services_dir.iterdir():
            if addon_dir.is_dir():
                reconcile_one(addon_dir)
        time.sleep(interval)

if __name__ == "__main__":
    main()

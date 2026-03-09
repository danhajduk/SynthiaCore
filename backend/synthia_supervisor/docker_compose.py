import os
import subprocess
import logging
import time
import hashlib
import shutil
from pathlib import Path
from typing import Iterable

log = logging.getLogger("synthia.supervisor")


def _normalize_tree_mtime(root: Path) -> None:
    now = time.time()
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            continue
        try:
            os.utime(path, (now, now))
        except FileNotFoundError:
            continue
    try:
        os.utime(root, (now, now))
    except FileNotFoundError:
        return


def _artifact_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _run_compose_command(args: list[str], action: str) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode == 0:
        return
    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    summary = stderr or stdout or f"exit_{proc.returncode}"
    tail_line = summary.splitlines()[-1] if summary else f"exit_{proc.returncode}"
    log.error(
        "%s_failed rc=%s summary=%s",
        action,
        proc.returncode,
        tail_line,
    )
    raise RuntimeError(f"{action}_failed: {tail_line}")


def _compose_files_list(compose_file: Path | Iterable[Path]) -> list[Path]:
    if isinstance(compose_file, Path):
        return [compose_file]
    return [Path(item) for item in compose_file]


def compose_up(compose_file: Path | Iterable[Path], project_name: str, *, force_rebuild: bool = False):
    compose_files = _compose_files_list(compose_file)
    log.info("compose_up project=%s files=%s", project_name, [str(item) for item in compose_files])
    cmd = ["docker", "compose"]
    for item in compose_files:
        cmd.extend(["-f", str(item)])
    base = [*cmd, "-p", project_name]
    if force_rebuild:
        build_cmd = [*base, "build", "--no-cache"]
        _run_compose_command(
            build_cmd,
            "compose_build",
        )
    cmd = [*base, "up", "-d", "--remove-orphans"]
    if force_rebuild:
        cmd.append("--force-recreate")
    _run_compose_command(
        cmd,
        "compose_up",
    )


def compose_down(compose_file: Path | Iterable[Path], project_name: str):
    compose_files = _compose_files_list(compose_file)
    log.info("compose_down project=%s files=%s", project_name, [str(item) for item in compose_files])
    cmd = ["docker", "compose"]
    for item in compose_files:
        cmd.extend(["-f", str(item)])
    cmd.extend(["-p", project_name, "down", "--remove-orphans"])
    _run_compose_command(
        cmd,
        "compose_down",
    )


def ensure_extracted(artifact_path: Path, extracted_dir: Path):
    artifact_hash = _artifact_sha256(artifact_path)
    marker_path = extracted_dir / ".artifact.sha256"
    runtime_dir = extracted_dir / "runtime"
    if extracted_dir.exists():
        marker_hash = ""
        if marker_path.exists():
            try:
                marker_hash = marker_path.read_text(encoding="utf-8").strip()
            except Exception:
                marker_hash = ""
        if artifact_hash and marker_hash != artifact_hash:
            log.info("extract_refresh path=%s reason=artifact_changed", extracted_dir)
            shutil.rmtree(extracted_dir, ignore_errors=True)
            extracted_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(["tar","-xzf",str(artifact_path),"-C",str(extracted_dir)], check=True)
            marker_path.write_text(f"{artifact_hash}\n", encoding="utf-8")
            runtime_dir.mkdir(parents=True, exist_ok=True)
            _normalize_tree_mtime(extracted_dir)
            log.info("extract_mtime_normalized path=%s", extracted_dir)
            log.info("runtime_dir_ensured path=%s", runtime_dir)
            log.info("extract_done dest=%s", extracted_dir)
            return
        log.info("extract_skip path=%s reason=already_exists", extracted_dir)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        _normalize_tree_mtime(extracted_dir)
        log.info("extract_mtime_normalized path=%s", extracted_dir)
        log.info("runtime_dir_ensured path=%s", runtime_dir)
        return
    log.info("extract_start artifact=%s dest=%s", artifact_path, extracted_dir)
    extracted_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar","-xzf",str(artifact_path),"-C",str(extracted_dir)], check=True)
    if artifact_hash:
        marker_path.write_text(f"{artifact_hash}\n", encoding="utf-8")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    _normalize_tree_mtime(extracted_dir)
    log.info("extract_mtime_normalized path=%s", extracted_dir)
    log.info("runtime_dir_ensured path=%s", runtime_dir)
    log.info("extract_done dest=%s", extracted_dir)


def ensure_compose_files(
    desired,
    extracted_dir: Path,
    compose_file: Path,
    env_file: Path,
    desired_file: Path,
    runtime_file: Path,
):
    env_values = dict(getattr(desired.config, "env", {}) or {})
    service_token = os.environ.get("SYNTHIA_SERVICE_TOKEN")
    if service_token:
        env_values.setdefault("SYNTHIA_SERVICE_TOKEN", service_token)
    env_lines = [f"{k}={v}" for k, v in sorted(env_values.items())]
    env_file.write_text("\n".join(env_lines) + ("\n" if env_lines else ""))
    log.info("runtime_env_written path=%s keys=%s", env_file, sorted(env_values.keys()))

    network_name = desired.runtime.network or "synthia_net"
    bind_localhost = bool(getattr(desired.runtime, "bind_localhost", True))
    host_bind = "127.0.0.1" if bind_localhost else "0.0.0.0"
    ports_yaml = ""
    for item in list(getattr(desired.runtime, "ports", []) or []):
        if not isinstance(item, dict):
            continue
        host = item.get("host")
        container = item.get("container")
        if host is None or container is None:
            continue
        proto = str(item.get("proto") or "tcp").lower()
        ports_yaml += f"      - \"{host_bind}:{int(host)}:{int(container)}/{proto}\"\n"
    ports_section = f"    ports:\n{ports_yaml}" if ports_yaml else ""
    cpu_limit = getattr(desired.runtime, "cpu", None)
    memory_limit = getattr(desired.runtime, "memory", None)
    cpu_section = f"    cpus: {float(cpu_limit)}\n" if cpu_limit is not None else ""
    memory_section = f"    mem_limit: {str(memory_limit).strip()}\n" if memory_limit else ""
    state_section = (
        "    volumes:\n"
        f"      - {desired_file}:/state/desired.json\n"
        f"      - {runtime_file}:/state/runtime.json\n"
        f"      - {compose_file}:/state/docker-compose.yml:ro\n"
    )
    compose_content = f"""
services:
  {desired.addon_id}:
    build: {extracted_dir}
    restart: unless-stopped
    privileged: false
    security_opt:
      - no-new-privileges:true
    env_file:
      - {env_file}
    networks:
      - {network_name}
{state_section}{cpu_section}{memory_section}{ports_section}

networks:
  {network_name}:
    name: {network_name}
"""
    if compose_file.exists():
        existing = compose_file.read_text(encoding="utf-8")
        stale_read_only_state_mount = (
            "/state/desired.json:ro" in existing or "/state/runtime.json:ro" in existing
        )
        if not stale_read_only_state_mount:
            log.info("compose_file_skip path=%s reason=already_exists", compose_file)
            return
        log.info("compose_file_regen path=%s reason=state_mount_mode_update", compose_file)
    compose_file.write_text(compose_content)
    log.info(
        "compose_file_written path=%s network=%s host_bind=%s",
        compose_file,
        network_name,
        host_bind,
    )

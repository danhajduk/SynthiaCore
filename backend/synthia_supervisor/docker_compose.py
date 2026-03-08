import os
import subprocess
import logging
from pathlib import Path
from typing import Iterable

log = logging.getLogger("synthia.supervisor")


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
    cmd.extend(["-p", project_name, "up", "-d", "--remove-orphans"])
    if force_rebuild:
        cmd.extend(["--build", "--force-recreate"])
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
    runtime_dir = extracted_dir / "runtime"
    if extracted_dir.exists():
        log.info("extract_skip path=%s reason=already_exists", extracted_dir)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        log.info("runtime_dir_ensured path=%s", runtime_dir)
        return
    log.info("extract_start artifact=%s dest=%s", artifact_path, extracted_dir)
    extracted_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar","-xzf",str(artifact_path),"-C",str(extracted_dir)], check=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log.info("runtime_dir_ensured path=%s", runtime_dir)
    log.info("extract_done dest=%s", extracted_dir)


def ensure_compose_files(desired, extracted_dir: Path, compose_file: Path, env_file: Path):
    env_values = dict(getattr(desired.config, "env", {}) or {})
    service_token = os.environ.get("SYNTHIA_SERVICE_TOKEN")
    if service_token:
        env_values.setdefault("SYNTHIA_SERVICE_TOKEN", service_token)
    env_lines = [f"{k}={v}" for k, v in sorted(env_values.items())]
    env_file.write_text("\n".join(env_lines) + ("\n" if env_lines else ""))
    log.info("runtime_env_written path=%s keys=%s", env_file, sorted(env_values.keys()))

    if compose_file.exists():
        log.info("compose_file_skip path=%s reason=already_exists", compose_file)
        return
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
    compose_file.write_text(f"""
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
{cpu_section}{memory_section}{ports_section}

networks:
  {network_name}:
    name: {network_name}
""")
    log.info(
        "compose_file_written path=%s network=%s host_bind=%s",
        compose_file,
        network_name,
        host_bind,
    )

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable
from urllib import error as urlerror
from urllib import request as urlrequest

from app.addons.discovery import repo_root

from .models import StandaloneAddonRuntime, StandaloneAddonRuntimeSnapshot

CommandRunner = Callable[[list[str]], tuple[int, str, str] | None]
HealthProbeRunner = Callable[[str, float], tuple[int | None, str | None, str | None]]
ServicesRootResolver = Callable[..., Path]
ServiceAddonDirResolver = Callable[..., Path]


def _resolve_from_backend_dir(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    backend_dir = repo_root() / "backend"
    return (backend_dir / path).resolve()


def _synthia_addons_dir() -> Path:
    raw = os.environ.get("SYNTHIA_ADDONS_DIR")
    if raw is None or not raw.strip():
        return (repo_root().parent / "SynthiaAddons").resolve()
    return _resolve_from_backend_dir(raw.strip())


def _default_services_root(*, create: bool = False) -> Path:
    path = _synthia_addons_dir() / "services"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _default_service_addon_dir(addon_id: str, *, create: bool = False) -> Path:
    cleaned = addon_id.strip()
    if not cleaned:
        raise ValueError("addon_id_empty")
    if "/" in cleaned or "\\" in cleaned or cleaned in {".", ".."}:
        raise ValueError("addon_id_invalid")
    path = _default_services_root(create=create) / cleaned
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json_dict(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        return None, str(exc) or type(exc).__name__
    if not isinstance(raw, dict):
        return None, "json_root_not_object"
    return raw, None


def _default_command_runner(cmd: list[str]) -> tuple[int, str, str] | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=4, check=False)
    except FileNotFoundError:
        return None
    except Exception as exc:  # pragma: no cover - defensive
        return 1, "", str(exc) or type(exc).__name__
    return proc.returncode, proc.stdout, proc.stderr


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = float(raw.strip())
    except Exception:
        return default
    if parsed <= 0:
        return default
    return parsed


def _default_health_probe(url: str, timeout_s: float) -> tuple[int | None, str | None, str | None]:
    req = urlrequest.Request(url, method="GET")
    try:
        with urlrequest.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return int(resp.status), body, None
    except urlerror.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        return int(exc.code), body, None
    except Exception as exc:
        return None, None, str(exc) or type(exc).__name__


def _normalize_health(value: Any) -> tuple[str, str | None]:
    if isinstance(value, dict):
        raw_status = str(value.get("status") or value.get("state") or "").strip().lower()
        detail = str(value.get("detail") or value.get("message") or value.get("error") or "").strip() or None
    elif isinstance(value, str):
        raw_status = value.strip().lower()
        detail = None
    else:
        return "unknown", None

    aliases = {
        "ok": "healthy",
        "pass": "healthy",
        "passing": "healthy",
        "healthy": "healthy",
        "unhealthy": "unhealthy",
        "fail": "unhealthy",
        "failing": "unhealthy",
        "error": "unhealthy",
    }
    status = aliases.get(raw_status)
    if status:
        return status, detail
    return "unknown", detail


def _normalize_lifecycle_state(value: Any, *, desired_state: str, runtime_state: str) -> str:
    raw = str(value or "").strip().lower()
    allowed = {"unknown", "starting", "running", "stopping", "stopped", "restarting", "error"}
    if raw in allowed:
        return raw
    if runtime_state == "running":
        return "running"
    if runtime_state == "stopped":
        return "stopped"
    if runtime_state == "error":
        return "error"
    if desired_state == "stopped":
        return "stopped"
    return "unknown"


def _ports_from_desired(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        return []
    ports: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        host = item.get("host")
        container = item.get("container")
        proto = str(item.get("protocol") or "tcp").strip().lower() or "tcp"
        if host is None or container is None:
            continue
        host_bind = "127.0.0.1" if bool(item.get("bind_localhost", True)) else "0.0.0.0"
        ports.append(f"{host_bind}:{host}->{container}/{proto}")
    return ports


def _ports_from_inspect(payload: dict[str, Any]) -> list[str]:
    network_settings = payload.get("NetworkSettings")
    if not isinstance(network_settings, dict):
        return []
    ports_payload = network_settings.get("Ports")
    if not isinstance(ports_payload, dict):
        return []

    ports: list[str] = []
    for container_port, bindings in ports_payload.items():
        if not isinstance(container_port, str):
            continue
        if bindings is None:
            ports.append(container_port)
            continue
        if not isinstance(bindings, list):
            continue
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            host_ip = str(binding.get("HostIp") or "0.0.0.0").strip() or "0.0.0.0"
            host_port = str(binding.get("HostPort") or "").strip()
            if not host_port:
                continue
            ports.append(f"{host_ip}:{host_port}->{container_port}")
    return ports


def _health_probe_url_from_ports(published_ports: list[str]) -> str | None:
    for entry in published_ports:
        text = str(entry).strip()
        if not text:
            continue
        try:
            mapping, container = text.split("->", 1)
            host, host_port = mapping.rsplit(":", 1)
            container_port, proto = container.split("/", 1)
        except ValueError:
            continue
        if str(proto).strip().lower() != "tcp":
            continue
        host = host.strip()
        host_port = host_port.strip()
        if not host_port.isdigit() or not str(container_port).strip().isdigit():
            continue
        probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        return f"http://{probe_host}:{host_port}/api/addon/health"
    return None


def _last_health_log_detail(health_payload: dict[str, Any]) -> str | None:
    logs = health_payload.get("Log")
    if not isinstance(logs, list) or not logs:
        return None
    latest = logs[-1]
    if not isinstance(latest, dict):
        return None
    output = str(latest.get("Output") or "").strip()
    if not output:
        return None
    return output[:300]


class StandaloneRuntimeService:
    def __init__(
        self,
        *,
        cmd_runner: CommandRunner | None = None,
        health_probe_runner: HealthProbeRunner | None = None,
        health_probe_enabled: bool | None = None,
        health_probe_timeout_s: float | None = None,
        services_root_resolver: ServicesRootResolver = _default_services_root,
        service_addon_dir_resolver: ServiceAddonDirResolver = _default_service_addon_dir,
    ) -> None:
        self._cmd_runner = cmd_runner or _default_command_runner
        self._health_probe_runner = health_probe_runner or _default_health_probe
        self._health_probe_enabled = (
            _env_flag("SYNTHIA_RUNTIME_HEALTH_PROBE_ENABLED", False)
            if health_probe_enabled is None
            else bool(health_probe_enabled)
        )
        self._health_probe_timeout_s = (
            _env_float("SYNTHIA_RUNTIME_HEALTH_PROBE_TIMEOUT_S", 2.0)
            if health_probe_timeout_s is None
            else float(health_probe_timeout_s)
        )
        self._services_root_resolver = services_root_resolver
        self._service_addon_dir_resolver = service_addon_dir_resolver

    def list_standalone_addon_runtimes(self) -> list[StandaloneAddonRuntime]:
        root = self._services_root_resolver(create=False)
        if not root.exists():
            return []

        runtimes: list[StandaloneAddonRuntime] = []
        for addon_dir in sorted(root.iterdir(), key=lambda item: item.name):
            if not addon_dir.is_dir() or addon_dir.name.startswith("."):
                continue
            runtimes.append(self.get_standalone_addon_runtime(addon_dir.name))
        return runtimes

    def get_standalone_addon_runtime(self, addon_id: str) -> StandaloneAddonRuntime:
        return self.get_standalone_addon_runtime_snapshot(addon_id).runtime

    def get_standalone_addon_runtime_snapshot(self, addon_id: str) -> StandaloneAddonRuntimeSnapshot:
        try:
            addon_dir = self._service_addon_dir_resolver(addon_id, create=False)
            resolve_error: str | None = None
        except Exception as exc:
            addon_dir = self._services_root_resolver(create=False) / str(addon_id).strip()
            resolve_error = str(exc) or type(exc).__name__
        desired_path = addon_dir / "desired.json"
        runtime_path = addon_dir / "runtime.json"

        desired_payload, desired_error = _read_json_dict(desired_path)
        runtime_payload, runtime_error = _read_json_dict(runtime_path)

        desired_state = "unknown"
        target_version: str | None = None
        project_name: str | None = None
        network: str | None = None
        published_ports: list[str] = []
        if isinstance(desired_payload, dict):
            desired_state = str(desired_payload.get("desired_state") or "unknown").strip() or "unknown"
            pinned_version = desired_payload.get("pinned_version")
            target_version = str(pinned_version).strip() if pinned_version is not None else None
            runtime_cfg = desired_payload.get("runtime")
            if isinstance(runtime_cfg, dict):
                project_name_raw = runtime_cfg.get("project_name")
                if project_name_raw is not None:
                    project_name = str(project_name_raw).strip() or None
                network_raw = runtime_cfg.get("network")
                if network_raw is not None:
                    network = str(network_raw).strip() or None
                published_ports = _ports_from_desired(runtime_cfg.get("ports"))

        runtime_state = "unknown"
        active_version: str | None = None
        health_status = "unknown"
        health_detail: str | None = None
        last_error: str | None = None
        lifecycle_state = "unknown"
        last_action: str | None = None
        last_action_at: str | None = None
        if isinstance(runtime_payload, dict):
            runtime_state = str(runtime_payload.get("state") or "unknown").strip() or "unknown"
            active_raw = runtime_payload.get("active_version")
            active_version = str(active_raw).strip() if active_raw is not None else None
            last_error_raw = runtime_payload.get("last_error") or runtime_payload.get("error")
            last_error = str(last_error_raw).strip() if last_error_raw is not None else None
            health_status, health_detail = _normalize_health(runtime_payload.get("health"))
            lifecycle_state = _normalize_lifecycle_state(
                runtime_payload.get("lifecycle_state"),
                desired_state=desired_state,
                runtime_state=runtime_state,
            )
            last_action_raw = runtime_payload.get("last_action")
            last_action = str(last_action_raw).strip() if last_action_raw is not None else None
            last_action_at_raw = runtime_payload.get("last_action_at")
            last_action_at = str(last_action_at_raw).strip() if last_action_at_raw is not None else None

        docker_meta, docker_error = self._inspect_compose_container(project_name)

        container_name: str | None = None
        container_status: str | None = None
        running: bool | None = None
        restart_count: int | None = None
        started_at: str | None = None

        if isinstance(docker_meta, dict):
            container_name = docker_meta.get("container_name")
            container_status = docker_meta.get("container_status")
            running = docker_meta.get("running")
            restart_count = docker_meta.get("restart_count")
            started_at = docker_meta.get("started_at")
            if not published_ports:
                published_ports = docker_meta.get("published_ports") or []
            network = network or docker_meta.get("network")
            if health_status == "unknown":
                health_status = str(docker_meta.get("health_status") or "unknown")
                health_detail = docker_meta.get("health_detail")
            if runtime_state == "unknown" and running is not None:
                runtime_state = "running" if running else "stopped"

        probe_status, probe_detail = self._probe_service_health(
            runtime_state=runtime_state,
            running=running,
            published_ports=published_ports,
        )
        if probe_status is not None:
            health_status = probe_status
            health_detail = probe_detail

        runtime = StandaloneAddonRuntime(
            addon_id=addon_id,
            desired_state=desired_state,
            runtime_state=runtime_state,
            lifecycle_state=lifecycle_state,
            active_version=active_version,
            target_version=target_version,
            container_name=container_name,
            container_status=container_status,
            running=running,
            restart_count=restart_count,
            started_at=started_at,
            health_status=health_status,
            health_detail=health_detail,
            published_ports=published_ports,
            network=network,
            last_error=last_error,
            last_action=last_action,
            last_action_at=last_action_at,
        )

        return StandaloneAddonRuntimeSnapshot(
            addon_id=addon_id,
            runtime=runtime,
            desired_path=str(desired_path.resolve()),
            runtime_path=str(runtime_path.resolve()),
            desired_error=desired_error or resolve_error,
            runtime_error=runtime_error,
            docker_error=docker_error,
            raw_desired=desired_payload,
            raw_runtime=runtime_payload,
        )

    def _probe_service_health(
        self,
        *,
        runtime_state: str,
        running: bool | None,
        published_ports: list[str],
    ) -> tuple[str | None, str | None]:
        if not self._health_probe_enabled:
            return None, None
        if running is False:
            return None, None
        if running is None and runtime_state != "running":
            return None, None

        probe_url = _health_probe_url_from_ports(published_ports)
        if not probe_url:
            return None, None

        status_code, body, probe_error = self._health_probe_runner(probe_url, self._health_probe_timeout_s)
        if probe_error:
            return "unhealthy", f"probe_error: {probe_error}"

        if status_code is None:
            return "unknown", "probe_no_status"
        if status_code == 404:
            return "unknown", "health_endpoint_missing"
        if status_code >= 500:
            return "unhealthy", f"probe_http_{status_code}"
        if status_code >= 400:
            return "unhealthy", f"probe_http_{status_code}"

        body_text = str(body or "").strip()
        if body_text:
            try:
                payload = json.loads(body_text)
            except Exception:
                payload = body_text
            status, detail = _normalize_health(payload)
            if status != "unknown":
                return status, detail
        return "healthy", f"probe_http_{status_code}"

    def _inspect_compose_container(self, project_name: str | None) -> tuple[dict[str, Any] | None, str | None]:
        if not project_name:
            return None, None

        ps_cmd = [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={project_name}",
            "--format",
            "{{json .}}",
        ]
        ps_result = self._cmd_runner(ps_cmd)
        if ps_result is None:
            return None, "docker_unavailable"
        returncode, stdout, stderr = ps_result
        if returncode != 0:
            detail = (stderr or stdout or "docker_ps_failed").strip() or "docker_ps_failed"
            return None, detail

        rows: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)

        if not rows:
            return None, None

        rows.sort(key=lambda item: str(item.get("Names") or ""))
        row = rows[0]
        container_name = str(row.get("Names") or "").strip()
        if not container_name:
            return None, None

        inspect_cmd = ["docker", "inspect", container_name]
        inspect_result = self._cmd_runner(inspect_cmd)
        if inspect_result is None:
            return None, "docker_unavailable"
        inspect_code, inspect_stdout, inspect_stderr = inspect_result
        if inspect_code != 0:
            detail = (inspect_stderr or inspect_stdout or "docker_inspect_failed").strip() or "docker_inspect_failed"
            return None, detail

        try:
            inspect_payload = json.loads(inspect_stdout)
        except Exception:
            return None, "docker_inspect_invalid_json"
        if not isinstance(inspect_payload, list) or not inspect_payload or not isinstance(inspect_payload[0], dict):
            return None, "docker_inspect_invalid_payload"

        container = inspect_payload[0]
        state_payload = container.get("State") if isinstance(container.get("State"), dict) else {}
        health_payload = state_payload.get("Health") if isinstance(state_payload.get("Health"), dict) else {}

        running = state_payload.get("Running")
        restart_count_raw = state_payload.get("RestartCount")
        try:
            restart_count = int(restart_count_raw) if restart_count_raw is not None else None
        except Exception:
            restart_count = None

        started_at_raw = str(state_payload.get("StartedAt") or "").strip()
        started_at = None if started_at_raw.startswith("0001-") or not started_at_raw else started_at_raw

        status_raw = str(state_payload.get("Status") or row.get("Status") or "").strip().lower()
        health_status, health_detail = _normalize_health(health_payload.get("Status"))
        if health_status == "unknown":
            health_status, health_detail = _normalize_health(health_payload)
        if not health_detail:
            health_detail = _last_health_log_detail(health_payload)

        host_config = container.get("HostConfig") if isinstance(container.get("HostConfig"), dict) else {}
        network_mode = str(host_config.get("NetworkMode") or "").strip() or None
        if not network_mode:
            network_settings = container.get("NetworkSettings")
            if isinstance(network_settings, dict):
                networks = network_settings.get("Networks")
                if isinstance(networks, dict) and networks:
                    network_mode = sorted(str(name) for name in networks.keys())[0]

        payload = {
            "container_name": str(container.get("Name") or container_name).lstrip("/") or container_name,
            "container_status": status_raw or None,
            "running": bool(running) if running is not None else None,
            "restart_count": restart_count,
            "started_at": started_at,
            "health_status": health_status,
            "health_detail": health_detail,
            "published_ports": _ports_from_inspect(container),
            "network": network_mode,
        }
        return payload, None

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlparse

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.system.runtime import StandaloneRuntimeService

from .config import supervisor_api_config
from .models import SupervisorCoreRuntimeHeartbeatRequest, SupervisorCoreRuntimeRegistrationRequest
from .router import build_supervisor_router
from .service import SupervisorDomainService

log = logging.getLogger(__name__)


def _env_text(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    return str(raw).strip() if raw is not None else default


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = _env_text(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "")).strip()
    try:
        return float(raw) if raw else default
    except Exception:
        return default


def _supervisor_identity() -> dict[str, str | None]:
    hostname = socket.gethostname()
    supervisor_id = (
        _env_text("HEXE_SUPERVISOR_ID")
        or _env_text("SYNTHIA_SUPERVISOR_ID")
        or f"{hostname}-supervisor"
    )
    return {
        "supervisor_id": supervisor_id,
        "supervisor_name": _env_text("HEXE_SUPERVISOR_NAME") or _env_text("SYNTHIA_SUPERVISOR_NAME") or supervisor_id,
        "supervisor_version": _env_text("SYNTHIA_CORE_VERSION", "0.1.0"),
        "host_id": _env_text("HEXE_SUPERVISOR_HOST_ID") or hostname,
        "hostname": hostname,
        "api_base_url": _env_text("HEXE_SUPERVISOR_PUBLIC_URL") or _env_text("HEXE_SUPERVISOR_API_BASE_URL") or None,
        "transport": _env_text("HEXE_SUPERVISOR_TRANSPORT", "socket"),
    }


def _supervisor_core_url() -> str:
    return (
        _env_text("HEXE_SUPERVISOR_CORE_URL")
        or _env_text("SYNTHIA_CORE_URL")
        or _env_text("CORE_URL")
    ).rstrip("/")


def _is_local_core_url(core_url: str) -> bool:
    if _env_bool("HEXE_SUPERVISOR_LOCAL_CORE", False):
        return True
    host = (urlparse(core_url).hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        local_ips = set(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        local_ips = set()
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2.0, check=False)
        if result.returncode == 0:
            local_ips.update(part.strip() for part in (result.stdout or "").split() if part.strip())
    except Exception:
        pass
    return host in local_ips


def _supervisor_core_token() -> str:
    return _env_text("HEXE_SUPERVISOR_CORE_TOKEN") or _env_text("SYNTHIA_ADMIN_TOKEN")


def _supervisor_core_token_kind() -> str:
    value = _env_text("HEXE_SUPERVISOR_CORE_TOKEN_KIND").lower()
    if value in {"supervisor", "admin"}:
        return value
    if _env_text("HEXE_SUPERVISOR_CORE_TOKEN").startswith("hexe_sup_report_"):
        return "supervisor"
    return "admin"


def _bluetooth_access_policy() -> str:
    value = _env_text("HEXE_BLUETOOTH_ACCESS_POLICY", "disabled").lower()
    if value in {"disabled", "ask", "trusted_only", "allowed"}:
        return value
    return "disabled"


def _supervisor_capabilities(resources: object | None = None, *, local_core_attached: bool = False) -> list[str]:
    capabilities = [
        "host_resources",
        "runtime_inventory",
        "node_runtime_registry",
        "core_runtime_registry",
    ]
    bluetooth_present = bool(getattr(resources, "bluetooth_present", False)) if resources is not None else False
    if bluetooth_present:
        capabilities.extend(["bluetooth", "bluetooth_governance"])
    if local_core_attached:
        capabilities.append("local_core_attached")
    return capabilities


def _supervisor_metadata(resources: object | None = None) -> dict[str, object]:
    metadata: dict[str, object] = {"reporter": "hexe-supervisor-api"}
    bluetooth_present = bool(getattr(resources, "bluetooth_present", False)) if resources is not None else False
    if bluetooth_present:
        metadata["bluetooth"] = {
            "present": True,
            "powered": bool(getattr(resources, "bluetooth_powered", False)),
            "ensure_powered": bool(getattr(resources, "bluetooth_ensure_powered", False)),
            "power_error": getattr(resources, "bluetooth_power_error", None),
            "policy": _bluetooth_access_policy(),
            "governed_by_core": True,
        }
    return metadata


def _build_core_registration_payload() -> dict[str, object]:
    payload: dict[str, object] = {key: value for key, value in _supervisor_identity().items() if value}
    payload["capabilities"] = _supervisor_capabilities()
    payload["metadata"] = _supervisor_metadata()
    return payload


def _systemd_runtime_payload(
    *,
    runtime_id: str,
    runtime_name: str,
    runtime_kind: str,
    unit: str,
    hostname: str,
) -> dict[str, object]:
    active_state = "unknown"
    sub_state = "unknown"
    load_state = "unknown"
    last_error = None
    try:
        result = subprocess.run(
            ["systemctl", "show", unit, "--property=ActiveState,SubState,LoadState", "--no-page"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
        if result.returncode == 0:
            props: dict[str, str] = {}
            for line in (result.stdout or "").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    props[key] = value
            active_state = props.get("ActiveState") or active_state
            sub_state = props.get("SubState") or sub_state
            load_state = props.get("LoadState") or load_state
        else:
            last_error = (result.stderr or result.stdout or "").strip() or f"systemctl exited {result.returncode}"
    except Exception as exc:
        last_error = str(exc)
    running = active_state == "active"
    health_status = "healthy" if running else ("unknown" if load_state == "not-found" else "unhealthy")
    return {
        "runtime_id": runtime_id,
        "runtime_name": runtime_name,
        "runtime_kind": runtime_kind,
        "management_mode": "monitor" if runtime_kind == "core_service" else "manage",
        "host_id": hostname,
        "hostname": hostname,
        "desired_state": "running",
        "runtime_state": active_state,
        "lifecycle_state": active_state,
        "health_status": health_status,
        "last_error": last_error,
        "running": running,
        "runtime_metadata": {
            "component": runtime_id,
            "systemd_unit": unit,
            "systemd_active_state": active_state,
            "systemd_sub_state": sub_state,
            "systemd_load_state": load_state,
            "observer": "local_supervisor",
        },
    }


def _collect_local_core_runtimes() -> list[dict[str, object]]:
    hostname = socket.gethostname()
    items = [
        _systemd_runtime_payload(
            runtime_id="core-api",
            runtime_name="Hexe Core API",
            runtime_kind="core_service",
            unit=_env_text("HEXE_CORE_SYSTEMD_UNIT", "hexe-backend.service"),
            hostname=hostname,
        ),
        _systemd_runtime_payload(
            runtime_id="supervisor-api",
            runtime_name="Hexe Supervisor API",
            runtime_kind="core_service",
            unit=_env_text("HEXE_SUPERVISOR_API_SYSTEMD_UNIT", "hexe-supervisor-api.service"),
            hostname=hostname,
        ),
        _systemd_runtime_payload(
            runtime_id="supervisor",
            runtime_name="Hexe Supervisor",
            runtime_kind="core_service",
            unit=_env_text("HEXE_SUPERVISOR_SYSTEMD_UNIT", "hexe-supervisor.service"),
            hostname=hostname,
        ),
    ]
    for unit in _env_list("HEXE_SUPERVISOR_LOCAL_AUX_UNITS", ["hexe-cloudflared.service", "cloudflared.service"]):
        runtime_id = unit.removesuffix(".service")
        items.append(
            _systemd_runtime_payload(
                runtime_id=runtime_id,
                runtime_name=runtime_id.replace("-", " ").title(),
                runtime_kind="aux_service",
                unit=unit,
                hostname=hostname,
            )
        )
    return [item for item in items if item.get("runtime_metadata", {}).get("systemd_load_state") != "not-found"]


def _build_core_heartbeat_payload(supervisor: SupervisorDomainService) -> dict[str, object]:
    identity = _supervisor_identity()
    health = supervisor.health_summary()
    resources = supervisor.resources_summary()
    runtime = supervisor.runtime_summary()
    registered_runtimes = supervisor.list_registered_runtimes()
    core_runtimes = supervisor.list_core_runtimes()
    payload: dict[str, object] = {key: value for key, value in identity.items() if value}
    payload.update(
        {
            "health_status": health.status,
            "lifecycle_state": "running",
            "resources": resources.model_dump(mode="json"),
            "runtime": runtime.model_dump(mode="json"),
            "managed_node_count": len(runtime.managed_nodes),
            "registered_runtime_count": len(registered_runtimes),
            "core_runtime_count": len(core_runtimes),
            "registered_runtimes": [item.model_dump(mode="json") for item in registered_runtimes],
            "core_runtimes": [item.model_dump(mode="json") for item in core_runtimes],
            "capabilities": _supervisor_capabilities(resources),
            "metadata": {
                **_supervisor_metadata(resources),
                "supervisor_api_transport": identity.get("transport") or "socket",
            },
        }
    )
    return payload


async def _post_supervisor_payload(
    client: httpx.AsyncClient,
    *,
    core_url: str,
    token: str,
    path: str,
    payload: dict[str, object],
) -> bool:
    header_name = "X-Supervisor-Token" if _supervisor_core_token_kind() == "supervisor" else "X-Admin-Token"
    try:
        response = await client.post(
            f"{core_url}{path}",
            json=payload,
            headers={header_name: token},
        )
        if response.status_code < 400:
            return True
        log.debug("Supervisor report failed: %s -> HTTP %s", path, response.status_code)
    except httpx.HTTPError as exc:
        log.debug("Supervisor report request failed: %s (%s)", path, exc)
    return False


async def _supervisor_core_report_loop(supervisor: SupervisorDomainService) -> None:
    core_url = _supervisor_core_url()
    token = _supervisor_core_token()
    if not core_url or not token:
        return
    local_core = _is_local_core_url(core_url)
    interval_s = max(5.0, _env_float("HEXE_SUPERVISOR_REPORT_INTERVAL_S", 15.0))
    timeout_s = max(2.0, _env_float("HEXE_SUPERVISOR_REPORT_TIMEOUT_S", 5.0))
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        registered = False
        while True:
            try:
                if not registered:
                    registered = await _post_supervisor_payload(
                        client,
                        core_url=core_url,
                        token=token,
                        path="/api/system/supervisors/register",
                        payload=_build_core_registration_payload(),
                    )
                if local_core:
                    core_runtime_items = await asyncio.to_thread(_collect_local_core_runtimes)
                    for item in core_runtime_items:
                        try:
                            await asyncio.to_thread(
                                supervisor.register_core_runtime,
                                SupervisorCoreRuntimeRegistrationRequest.model_validate(item),
                            )
                            await asyncio.to_thread(
                                supervisor.heartbeat_core_runtime,
                                SupervisorCoreRuntimeHeartbeatRequest.model_validate(
                                    {
                                        "runtime_id": item.get("runtime_id"),
                                        "host_id": item.get("host_id"),
                                        "hostname": item.get("hostname"),
                                        "runtime_state": item.get("runtime_state"),
                                        "lifecycle_state": item.get("lifecycle_state"),
                                        "health_status": item.get("health_status"),
                                        "last_error": item.get("last_error"),
                                        "running": item.get("running"),
                                        "resource_usage": item.get("resource_usage", {}),
                                        "runtime_metadata": item.get("runtime_metadata", {}),
                                    }
                                ),
                            )
                        except Exception:
                            log.debug("Failed to refresh local core runtime %s", item.get("runtime_id"), exc_info=True)
                    await _post_supervisor_payload(
                        client,
                        core_url=core_url,
                        token=token,
                        path="/api/system/supervisors/local/core-runtimes",
                        payload={
                            "supervisor_id": _supervisor_identity().get("supervisor_id"),
                            "core_runtimes": core_runtime_items,
                        },
                    )
                heartbeat_payload = await asyncio.to_thread(_build_core_heartbeat_payload, supervisor)
                await _post_supervisor_payload(
                    client,
                    core_url=core_url,
                    token=token,
                    path="/api/system/supervisors/heartbeat",
                    payload=heartbeat_payload,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("Supervisor Core report loop failed", exc_info=True)
            await asyncio.sleep(interval_s)


def create_supervisor_app() -> FastAPI:
    runtime_service = StandaloneRuntimeService()
    supervisor = SupervisorDomainService(runtime_service=runtime_service)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task: asyncio.Task | None = None
        if (
            _env_bool("HEXE_SUPERVISOR_REPORT_ENABLED", True)
            and _supervisor_core_url()
            and _supervisor_core_token()
        ):
            task = asyncio.create_task(_supervisor_core_report_loop(supervisor))
            app.state.supervisor_core_report_task = task
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="Hexe Supervisor", version="0.1.0", lifespan=lifespan)
    app.state.supervisor_service = supervisor
    app.include_router(build_supervisor_router(supervisor), prefix="/api")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def readiness() -> JSONResponse:
        supervisor_service = getattr(app.state, "supervisor_service", supervisor)
        admission = supervisor_service.admission_summary()
        payload = {
            "status": "ready" if admission.execution_host_ready else "degraded",
            "admission": admission.model_dump(),
        }
        status_code = 200 if admission.execution_host_ready else 503
        return JSONResponse(content=payload, status_code=status_code)

    return app


def _prepare_unix_socket(path: str) -> None:
    socket_path = Path(path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()


def _init_boot_log(path: str) -> None:
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    log_path.write_text(f"{ts} [supervisor_boot] Supervisor API boot\n", encoding="utf-8")


def run() -> None:
    config = supervisor_api_config()
    log_level = str(os.getenv("HEXE_SUPERVISOR_LOG_LEVEL", "INFO")).strip().lower() or "info"
    boot_log_path = str(os.getenv("HEXE_SUPERVISOR_BOOT_LOG", "var/supervisor/boot.log")).strip() or "var/supervisor/boot.log"
    try:
        _init_boot_log(boot_log_path)
    except Exception:
        logging.getLogger(__name__).warning("Supervisor boot log init failed", exc_info=True)
    app = create_supervisor_app()

    if config.transport == "socket":
        _prepare_unix_socket(config.unix_socket)
        uvicorn.run(app, uds=config.unix_socket, log_level=log_level)
        return

    uvicorn.run(app, host=config.bind_host, port=config.port, log_level=log_level)


if __name__ == "__main__":
    run()

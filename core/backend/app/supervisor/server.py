from __future__ import annotations

import asyncio
import logging
import os
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.system.runtime import StandaloneRuntimeService

from .config import supervisor_api_config
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


def _supervisor_core_token() -> str:
    return _env_text("HEXE_SUPERVISOR_CORE_TOKEN") or _env_text("SYNTHIA_ADMIN_TOKEN")


def _supervisor_core_token_kind() -> str:
    value = _env_text("HEXE_SUPERVISOR_CORE_TOKEN_KIND").lower()
    if value in {"supervisor", "admin"}:
        return value
    if _env_text("HEXE_SUPERVISOR_CORE_TOKEN").startswith("hexe_sup_report_"):
        return "supervisor"
    return "admin"


def _build_core_registration_payload() -> dict[str, object]:
    payload: dict[str, object] = {key: value for key, value in _supervisor_identity().items() if value}
    payload["capabilities"] = [
        "host_resources",
        "runtime_inventory",
        "node_runtime_registry",
        "core_runtime_registry",
    ]
    payload["metadata"] = {"reporter": "hexe-supervisor-api"}
    return payload


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
            "capabilities": [
                "host_resources",
                "runtime_inventory",
                "node_runtime_registry",
                "core_runtime_registry",
            ],
            "metadata": {
                "reporter": "hexe-supervisor-api",
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

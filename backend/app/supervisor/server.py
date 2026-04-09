from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.system.runtime import StandaloneRuntimeService

from .config import supervisor_api_config
from .router import build_supervisor_router
from .service import SupervisorDomainService


def create_supervisor_app() -> FastAPI:
    app = FastAPI(title="Hexe Supervisor", version="0.1.0")
    runtime_service = StandaloneRuntimeService()
    supervisor = SupervisorDomainService(runtime_service=runtime_service)
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

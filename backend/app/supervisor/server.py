from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI

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
    return app


def _prepare_unix_socket(path: str) -> None:
    socket_path = Path(path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()


def run() -> None:
    config = supervisor_api_config()
    log_level = str(os.getenv("HEXE_SUPERVISOR_LOG_LEVEL", "INFO")).strip().lower() or "info"
    app = create_supervisor_app()

    if config.transport == "socket":
        _prepare_unix_socket(config.unix_socket)
        uvicorn.run(app, uds=config.unix_socket, log_level=log_level)
        return

    uvicorn.run(app, host=config.bind_host, port=config.port, log_level=log_level)


if __name__ == "__main__":
    run()

from __future__ import annotations

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.health import router as health_router
from .addons.registry import build_registry, register_addons
from .api.system import build_system_router

from .api.admin import router as admin_router
from .system.stats.router import router as stats_router

logging.basicConfig(level=logging.INFO)

def create_app() -> FastAPI:
    app = FastAPI(title="Synthia Core", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Core routes
    app.include_router(health_router, prefix="/api")

    # Admin routes
    app.include_router(admin_router, prefix="/api")

    # System stats routes
    app.include_router(stats_router, prefix="/api")

    # Addons
    registry = build_registry()
    register_addons(app, registry)

    # System API using the registry
    app.include_router(build_system_router(registry), prefix="/api")

    return app

app = create_app()

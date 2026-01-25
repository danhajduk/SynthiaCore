from __future__ import annotations

import logging
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.health import router as health_router
from .addons.registry import build_registry, register_addons
from .api.system import build_system_router
from .system.api_metrics import ApiMetricsCollector, ApiMetricsMiddleware
from .system.sampler import stats_sampler_loop

from .api.admin import router as admin_router
from .system.stats.router import router as stats_router

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    app = FastAPI(title="Synthia Core", version="0.1.0")

    api_metrics = ApiMetricsCollector()
    app.state.api_metrics = api_metrics

    app.add_middleware(
        ApiMetricsMiddleware,
        collector=api_metrics,
        trust_proxy_headers=False,
    )

    @app.on_event("startup")
    async def start_background_tasks():
        asyncio.create_task(stats_sampler_loop())

    api_metrics = ApiMetricsCollector()
    app.add_middleware(
        ApiMetricsMiddleware,
        collector=api_metrics,
        trust_proxy_headers=False,   # set True ONLY if nginx is in front and locked down
    )

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

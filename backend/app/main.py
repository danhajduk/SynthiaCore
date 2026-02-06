# /backend/app/main.py
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.logging import setup_logging
from .core.health import router as health_router
from .addons.registry import build_registry, register_addons
from .api.system import build_system_router
from .system.api_metrics import ApiMetricsCollector, ApiMetricsMiddleware
from app.system.sampler import (
    stats_fast_sampler_loop,
    api_metrics_sampler_loop,
    stats_minute_writer_loop,
)
from app.system.config import load_config

from .api.admin import router as admin_router
from .system.stats.router import router as stats_router

# NEW: scheduler components
from app.system.scheduler.store import SchedulerStore
from app.system.scheduler.engine import SchedulerEngine
from app.system.scheduler.history import SchedulerHistoryStore
from app.system.settings.store import SettingsStore
from app.system.settings.router import build_settings_router
from app.system.repo_status import router as repo_status_router
from app.system.scheduler import build_scheduler_router

setup_logging()
log = logging.getLogger("synthia.core")


def create_app() -> FastAPI:
    app = FastAPI(title="Synthia Core", version="0.1.0")
    log.info("Starting Synthia Core")

    api_metrics = ApiMetricsCollector()
    app.state.api_metrics = api_metrics

    app.add_middleware(
        ApiMetricsMiddleware,
        collector=api_metrics,
        trust_proxy_headers=False,
    )

    @app.on_event("startup")
    async def start_background_tasks():
        log.info("Starting background tasks for stats sampling and API metrics")
        cfg = load_config()
        app.state.system_config = cfg
        app.state.latest_stats = None
        app.state.latest_api_metrics = None
        app.state.latest_system_snapshot = None

        asyncio.create_task(stats_fast_sampler_loop(app, interval_s=cfg.stats_fast_interval_s))
        asyncio.create_task(
            api_metrics_sampler_loop(
                app,
                window_s=cfg.api_metrics_window_s,
                top_n=10,
                interval_s=cfg.api_metrics_interval_s,
            )
        )
        asyncio.create_task(stats_minute_writer_loop(app, retention_days=cfg.stats_retention_days))

        async def history_cleanup_loop() -> None:
            while True:
                try:
                    history_store = getattr(app.state, "scheduler_history", None)
                    if history_store:
                        await history_store.cleanup(days=30)
                except Exception:
                    pass
                await asyncio.sleep(timedelta(days=1).total_seconds())

        asyncio.create_task(history_cleanup_loop())

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

    # --------------------
    # Scheduler (NEW wiring)
    # --------------------
    store = SchedulerStore()
    history_db = os.getenv(
        "SCHEDULER_HISTORY_DB",
        os.path.join(os.getcwd(), "var", "scheduler_history.db"),
    )
    history_store = SchedulerHistoryStore(history_db)
    settings_db = os.getenv(
        "APP_SETTINGS_DB",
        os.path.join(os.getcwd(), "var", "app_settings.db"),
    )
    settings_store = SettingsStore(settings_db)

    def metrics_provider():
        # SchedulerEngine will handle None/staleness conservatively.
        return (
            getattr(app.state, "latest_stats", None),
            getattr(app.state, "latest_api_metrics", None),
        )

    engine = SchedulerEngine(
        store=store,
        metrics_provider=metrics_provider,
        history_store=history_store,
    )

    # make available to the rest of the app (debugging / future hooks)
    app.state.scheduler_store = store
    app.state.scheduler_engine = engine
    app.state.scheduler_history = history_store
    app.state.settings_store = settings_store

    app.include_router(build_settings_router(settings_store), prefix="/api/system", tags=["settings"])
    app.include_router(repo_status_router, prefix="/api/system", tags=["repo"])

    scheduler_router = build_scheduler_router(engine)
    app.include_router(scheduler_router, prefix="/api/system/scheduler", tags=["scheduler"])

    # Addons
    log.info("Building addon registry and registering addons")
    registry = build_registry()
    app.state.addon_registry = registry
    register_addons(app, registry)

    # System API using the registry
    app.include_router(build_system_router(registry), prefix="/api")

    return app


app = create_app()

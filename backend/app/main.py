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
from .addons.proxy import AddonProxy, build_proxy_router
from .api.system import build_system_router
from .api.admin_registry import build_admin_registry_router
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
from app.system.mqtt import MqttManager, build_mqtt_router
from app.system.services import ServiceCatalogStore, build_service_resolution_router
from app.system.auth import ServiceTokenKeyStore, build_auth_router
from app.system.policy import PolicyStore, build_policy_router
from app.system.telemetry import UsageTelemetryStore, build_telemetry_router
from app.system.audit import AuditLogStore
from app.system.repo_status import router as repo_status_router
from app.system.scheduler import build_scheduler_router
from app.store import build_store_models_router, StoreAuditLogStore, StoreSourcesStore, build_store_router

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

        async def addon_health_poll_loop() -> None:
            while True:
                try:
                    registry = getattr(app.state, "addon_registry", None)
                    if registry is not None:
                        await registry.refresh_registered_health()
                except Exception:
                    pass
                await asyncio.sleep(30.0)

        asyncio.create_task(addon_health_poll_loop())
        mqtt_manager = getattr(app.state, "mqtt_manager", None)
        if mqtt_manager is not None:
            await mqtt_manager.start()

    @app.on_event("shutdown")
    async def shutdown_background_tasks():
        proxy = getattr(app.state, "addon_proxy", None)
        if proxy is not None:
            await proxy.aclose()
        mqtt_manager = getattr(app.state, "mqtt_manager", None)
        if mqtt_manager is not None:
            await mqtt_manager.stop()

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
    service_token_keys = ServiceTokenKeyStore(settings_store)
    service_catalog_db = os.getenv(
        "SERVICE_CATALOG_DB",
        os.path.join(os.getcwd(), "var", "service_catalogs.json"),
    )
    service_catalog_store = ServiceCatalogStore(service_catalog_db)
    policy_grants_db = os.getenv(
        "POLICY_GRANTS_DB",
        os.path.join(os.getcwd(), "var", "policy_grants.json"),
    )
    policy_revocations_db = os.getenv(
        "POLICY_REVOCATIONS_DB",
        os.path.join(os.getcwd(), "var", "policy_revocations.json"),
    )
    policy_store = PolicyStore(policy_grants_db, policy_revocations_db)
    telemetry_db = os.getenv(
        "TELEMETRY_USAGE_DB",
        os.path.join(os.getcwd(), "var", "telemetry_usage.db"),
    )
    telemetry_store = UsageTelemetryStore(telemetry_db)
    audit_log_path = os.getenv(
        "AUDIT_LOG_PATH",
        os.path.join(os.getcwd(), "var", "audit.log"),
    )
    audit_store = AuditLogStore(audit_log_path)
    store_audit_db = os.getenv(
        "STORE_AUDIT_DB",
        os.path.join(os.getcwd(), "var", "store_audit.db"),
    )
    store_audit_store = StoreAuditLogStore(store_audit_db)
    store_sources_path = os.getenv(
        "STORE_SOURCES_DB",
        os.path.join(os.getcwd(), "var", "store_sources.json"),
    )
    store_sources_store = StoreSourcesStore(store_sources_path)

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
    app.state.service_token_keys = service_token_keys
    app.state.service_catalog_store = service_catalog_store
    app.state.policy_store = policy_store
    app.state.telemetry_store = telemetry_store
    app.state.audit_store = audit_store
    app.state.store_audit_store = store_audit_store
    app.state.store_sources_store = store_sources_store

    app.include_router(build_settings_router(settings_store, audit_store), prefix="/api/system", tags=["settings"])
    app.include_router(repo_status_router, prefix="/api/system", tags=["repo"])

    scheduler_cfg = load_config()
    scheduler_router = build_scheduler_router(
        engine,
        debug_enabled=bool(getattr(scheduler_cfg, "scheduler_debug_enabled", False)),
    )
    app.include_router(scheduler_router, prefix="/api/system/scheduler", tags=["scheduler"])

    # Addons
    log.info("Building addon registry and registering addons")
    registry = build_registry()
    app.state.addon_registry = registry
    mqtt_manager = MqttManager(
        settings_store=settings_store,
        registry=registry,
        service_catalog_store=service_catalog_store,
    )
    app.state.mqtt_manager = mqtt_manager
    register_addons(app, registry)
    addon_proxy = AddonProxy(registry)
    app.state.addon_proxy = addon_proxy
    app.include_router(build_proxy_router(addon_proxy))

    # System API using the registry
    app.include_router(build_system_router(registry), prefix="/api")
    app.include_router(build_admin_registry_router(registry), prefix="/api")
    app.include_router(build_mqtt_router(mqtt_manager), prefix="/api/system", tags=["mqtt"])
    app.include_router(build_auth_router(service_token_keys), prefix="/api/auth", tags=["auth"])
    app.include_router(build_policy_router(policy_store, mqtt_manager, audit_store), prefix="/api/policy", tags=["policy"])
    app.include_router(build_telemetry_router(telemetry_store, service_token_keys), prefix="/api/telemetry", tags=["telemetry"])
    app.include_router(
        build_service_resolution_router(registry, service_catalog_store),
        prefix="/api/services",
        tags=["services"],
    )
    app.include_router(build_store_models_router(), prefix="/api/store", tags=["store"])
    app.include_router(
        build_store_router(registry, store_audit_store, store_sources_store),
        prefix="/api/store",
        tags=["store"],
    )

    return app


app = create_app()

# /backend/app/main.py
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.logging import setup_logging
from .core.health import router as health_router
from .addons.registry import build_registry, register_addons
from .addons.install_sessions import InstallSessionsStore
from .addons.proxy import AddonProxy, build_proxy_router
from .api.system import build_system_router
from .api.admin_registry import build_admin_registry_router
from .api.addons_registry import build_addons_registry_router
from .api.addons_install import build_addons_install_router
from .system.api_metrics import ApiMetricsCollector, ApiMetricsMiddleware
from app.system.sampler import (
    stats_fast_sampler_loop,
    api_metrics_sampler_loop,
    stats_minute_writer_loop,
)
from app.system.config import load_config

from .api.admin import router as admin_router, configure_admin_users_store
from .system.stats.router import router as stats_router

# NEW: scheduler components
from app.system.scheduler.store import SchedulerStore
from app.system.scheduler.engine import SchedulerEngine
from app.system.scheduler.history import SchedulerHistoryStore
from app.system.settings.store import SettingsStore
from app.system.settings.router import build_settings_router
from app.system.mqtt import (
    EmbeddedMqttStartupReconciler,
    InMemoryBrokerRuntimeBoundary,
    MqttAclCompiler,
    MqttAuthorityAuditStore,
    MqttBrokerConfigRenderer,
    MqttIntegrationStateStore,
    MqttManager,
    MqttRegistrationApprovalService,
    MqttApplyPipeline,
    build_mqtt_router,
)
from app.system.events import PlatformEventService, build_events_router
from app.system.services import ServiceCatalogStore, build_service_resolution_router
from app.system.auth import ServiceTokenKeyStore, build_auth_router
from app.system.policy import PolicyStore, build_policy_router
from app.system.telemetry import UsageTelemetryStore, build_telemetry_router
from app.system.audit import AuditLogStore
from app.system.users import UsersStore, build_users_router
from app.system.runtime import StandaloneRuntimeService
from app.system.repo_status import router as repo_status_router
from app.system.stack_health import build_stack_health_router, speed_sampler_loop
from app.system.scheduler import build_scheduler_router
from app.store import CatalogCacheClient, build_store_models_router, StoreAuditLogStore, StoreSourcesStore, build_store_router
from app.store.catalog import catalog_refresh_due

setup_logging()
log = logging.getLogger("synthia.core")


def create_app() -> FastAPI:
    app = FastAPI(title="Synthia Core", version="0.1.0")
    log.info("Starting Synthia Core")
    cfg_boot = load_config()

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

        async def store_catalog_refresh_loop() -> None:
            while True:
                try:
                    sources_store = getattr(app.state, "store_sources_store", None)
                    catalog_client = getattr(app.state, "store_catalog_client", None)
                    if sources_store is not None and catalog_client is not None:
                        sources = await sources_store.list_sources()
                        for source in sources:
                            if not bool(getattr(source, "enabled", False)):
                                continue
                            load_metadata = getattr(catalog_client, "load_source_metadata", None)
                            refresh_source = getattr(catalog_client, "refresh_source", None)
                            metadata = load_metadata(source.id) if callable(load_metadata) else {}
                            if not isinstance(metadata, dict):
                                metadata = {}
                            if callable(refresh_source) and catalog_refresh_due(source, metadata):
                                await asyncio.to_thread(refresh_source, source)
                except Exception:
                    log.exception("Store catalog auto-refresh loop failed")
                await asyncio.sleep(300.0)

        asyncio.create_task(store_catalog_refresh_loop())
        asyncio.create_task(speed_sampler_loop())
        users_store = getattr(app.state, "users_store", None)
        if users_store is not None:
            await users_store.ensure_admin_user(seeded_admin_username, seeded_admin_password)
        mqtt_manager = getattr(app.state, "mqtt_manager", None)
        if mqtt_manager is not None:
            await mqtt_manager.start()
        mqtt_startup_reconciler = getattr(app.state, "mqtt_startup_reconciler", None)
        if mqtt_startup_reconciler is not None:
            try:
                await mqtt_startup_reconciler.reconcile_startup()
            except Exception:
                log.exception("Embedded MQTT startup reconciliation failed")

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
    mqtt_integration_state_db = os.getenv(
        "MQTT_INTEGRATION_STATE_DB",
        os.path.join(os.getcwd(), "var", "mqtt_integration_state.json"),
    )
    mqtt_integration_state_store = MqttIntegrationStateStore(mqtt_integration_state_db)
    mqtt_authority_audit_db = os.getenv(
        "MQTT_AUTHORITY_AUDIT_DB",
        os.path.join(os.getcwd(), "var", "mqtt_authority_audit.db"),
    )
    mqtt_authority_audit = MqttAuthorityAuditStore(mqtt_authority_audit_db)
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
    users_db = os.getenv(
        "APP_USERS_DB",
        os.path.join(os.getcwd(), "var", "users.db"),
    )
    users_store = UsersStore(users_db)
    seeded_admin_username = os.getenv("SYNTHIA_ADMIN_USERNAME", "admin").strip() or "admin"
    seeded_admin_password = os.getenv("SYNTHIA_ADMIN_PASSWORD", "") or os.getenv("SYNTHIA_ADMIN_TOKEN", "")

    # Admin routes
    configure_admin_users_store(users_store)
    app.include_router(admin_router, prefix="/api")

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
    app.state.mqtt_integration_state_store = mqtt_integration_state_store
    app.state.mqtt_authority_audit = mqtt_authority_audit
    app.state.policy_store = policy_store
    app.state.telemetry_store = telemetry_store
    app.state.audit_store = audit_store
    app.state.store_audit_store = store_audit_store
    app.state.store_sources_store = store_sources_store
    app.state.users_store = users_store
    install_sessions_store = InstallSessionsStore()
    app.state.install_sessions_store = install_sessions_store

    app.include_router(build_settings_router(settings_store, audit_store), prefix="/api/system", tags=["settings"])
    app.include_router(build_users_router(users_store, audit_store), prefix="/api/admin", tags=["admin-users"])
    app.include_router(repo_status_router, prefix="/api/system", tags=["repo"])
    app.include_router(build_stack_health_router(), prefix="/api/system", tags=["stack-health"])

    event_service = PlatformEventService()
    app.state.platform_events = event_service

    scheduler_router = build_scheduler_router(
        engine,
        debug_enabled=bool(getattr(cfg_boot, "scheduler_debug_enabled", False)),
        events=event_service,
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
        install_sessions_store=install_sessions_store,
        events=event_service,
        enabled=bool(getattr(cfg_boot, "mqtt_listener_enabled", True)),
    )
    app.state.mqtt_manager = mqtt_manager
    mqtt_registration_approval = MqttRegistrationApprovalService(
        registry=registry,
        state_store=mqtt_integration_state_store,
    )
    app.state.mqtt_registration_approval = mqtt_registration_approval
    mqtt_runtime_boundary = InMemoryBrokerRuntimeBoundary(provider="embedded_mosquitto")
    mqtt_acl_compiler = MqttAclCompiler()
    mqtt_config_renderer = MqttBrokerConfigRenderer()
    mqtt_apply_pipeline = MqttApplyPipeline(
        runtime_boundary=mqtt_runtime_boundary,
        audit_store=mqtt_authority_audit,
        live_dir=os.path.join(os.getcwd(), "var", "mqtt_runtime", "live"),
    )
    mqtt_startup_reconciler = EmbeddedMqttStartupReconciler(
        state_store=mqtt_integration_state_store,
        acl_compiler=mqtt_acl_compiler,
        config_renderer=mqtt_config_renderer,
        apply_pipeline=mqtt_apply_pipeline,
        audit_store=mqtt_authority_audit,
        mqtt_manager=mqtt_manager,
    )
    app.state.mqtt_runtime_boundary = mqtt_runtime_boundary
    app.state.mqtt_acl_compiler = mqtt_acl_compiler
    app.state.mqtt_config_renderer = mqtt_config_renderer
    app.state.mqtt_apply_pipeline = mqtt_apply_pipeline
    app.state.mqtt_startup_reconciler = mqtt_startup_reconciler
    register_addons(app, registry)
    addon_proxy = AddonProxy(registry)
    app.state.addon_proxy = addon_proxy

    # System API using the registry
    runtime_service = StandaloneRuntimeService()
    app.state.standalone_runtime_service = runtime_service
    app.include_router(build_system_router(registry, runtime_service, mqtt_registration_approval), prefix="/api")
    app.include_router(build_addons_registry_router(registry), prefix="/api")
    app.include_router(build_addons_install_router(registry, install_sessions_store), prefix="/api")
    app.include_router(build_admin_registry_router(registry, mqtt_registration_approval), prefix="/api")
    app.include_router(
        build_mqtt_router(mqtt_manager, registry, mqtt_integration_state_store, service_token_keys),
        prefix="/api/system",
        tags=["mqtt"],
    )
    app.include_router(build_events_router(event_service), prefix="/api/system", tags=["events"])
    app.include_router(build_auth_router(service_token_keys), prefix="/api/auth", tags=["auth"])
    app.include_router(build_policy_router(policy_store, mqtt_manager, audit_store), prefix="/api/policy", tags=["policy"])
    app.include_router(build_telemetry_router(telemetry_store, service_token_keys), prefix="/api/telemetry", tags=["telemetry"])
    app.include_router(
        build_service_resolution_router(registry, service_catalog_store, service_token_keys, event_service),
        prefix="/api/services",
        tags=["services"],
    )
    app.include_router(build_store_models_router(), prefix="/api/store", tags=["store"])
    catalog_cache_client = CatalogCacheClient(
        cache_root=CatalogCacheClient.from_default_path().cache_root,
        catalog_public_keys_path=Path(cfg_boot.store_catalog_public_keys_path),
        catalog_public_keys_json=cfg_boot.store_catalog_public_keys_json,
    )
    app.state.store_catalog_client = catalog_cache_client
    app.include_router(
        build_store_router(
            registry,
            store_audit_store,
            store_sources_store,
            catalog_cache_client,
            events=event_service,
            mqtt_approval_service=mqtt_registration_approval,
        ),
        prefix="/api/store",
        tags=["store"],
    )
    app.include_router(build_proxy_router(addon_proxy))

    return app


app = create_app()

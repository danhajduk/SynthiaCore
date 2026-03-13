# /backend/app/main.py
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core import CoreNotificationPublisher
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
from app.system.onboarding import (
    ModelRoutingRegistryService,
    ModelRoutingRegistryStore,
    NodeCapabilityAcceptanceService,
    NodeCapabilityProfilesStore,
    NodeGovernanceService,
    NodeGovernanceStatusService,
    NodeGovernanceStatusStore,
    NodeGovernanceStore,
    NodeTelemetryService,
    NodeTelemetryStore,
    NodeOnboardingSessionsStore,
    ProviderModelApprovalPolicyService,
    ProviderModelPolicyStore,
    NodeRegistrationsStore,
    NodeTrustIssuanceService,
    NodeTrustStore,
)
from app.system.mqtt import (
    DockerMosquittoRuntimeBoundary,
    EmbeddedMqttStartupReconciler,
    InMemoryBrokerRuntimeBoundary,
    MqttAclCompiler,
    MqttAuthorityAuditStore,
    MqttBrokerConfigRenderer,
    MqttCredentialStore,
    MqttIntegrationStateStore,
    MqttManager,
    MqttNoisyClientEvaluator,
    MqttObservabilityStore,
    MqttRegistrationApprovalService,
    MqttSetupStateUpdate,
    MqttApplyPipeline,
    ensure_runtime_dirs,
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

        async def onboarding_session_maintenance_loop() -> None:
            while True:
                try:
                    sessions_store = getattr(app.state, "node_onboarding_sessions_store", None)
                    if sessions_store is not None:
                        sessions_store.expire_stale_sessions()
                        retention_days_raw = str(os.getenv("SYNTHIA_NODE_ONBOARDING_ARCHIVE_RETAIN_DAYS", "30")).strip()
                        try:
                            retention_days = int(retention_days_raw)
                        except Exception:
                            retention_days = 30
                        if retention_days > 0:
                            sessions_store.archive_and_prune_terminal_sessions(retain_days=retention_days)
                except Exception:
                    log.exception("Node onboarding session maintenance loop failed")
                await asyncio.sleep(3600.0)

        asyncio.create_task(onboarding_session_maintenance_loop())

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
        mqtt_approval = getattr(app.state, "mqtt_registration_approval", None)
        addon_registry = getattr(app.state, "addon_registry", None)
        if mqtt_approval is not None and addon_registry is not None:
            try:
                if addon_registry.has_addon("mqtt") and addon_registry.is_enabled("mqtt"):
                    await mqtt_approval.reconcile("mqtt")
            except Exception:
                log.exception("MQTT startup addon principal reconciliation failed for addon:mqtt")

        async def mqtt_runtime_supervision_loop() -> None:
            while True:
                try:
                    runtime = getattr(app.state, "mqtt_runtime_boundary", None)
                    state_store = getattr(app.state, "mqtt_integration_state_store", None)
                    audit = getattr(app.state, "mqtt_authority_audit", None)
                    mqtt_manager = getattr(app.state, "mqtt_manager", None)
                    mqtt_obsv = getattr(app.state, "mqtt_observability_store", None)
                    startup_reconciler = getattr(app.state, "mqtt_startup_reconciler", None)
                    noisy_evaluator = getattr(app.state, "mqtt_noisy_evaluator", None)
                    if runtime is not None and state_store is not None:
                        status = await runtime.health_check()
                        if not status.healthy:
                            status = await runtime.ensure_running()
                            if (
                                not status.healthy
                                and str(getattr(status, "degraded_reason", "") or "").lower().startswith("config_missing")
                                and startup_reconciler is not None
                            ):
                                await startup_reconciler.reconcile_authority(reason="runtime_supervisor_config_missing")
                                status = await runtime.ensure_running()
                        state = await state_store.get_state()
                        if not status.healthy:
                            await state_store.update_setup_state(
                                MqttSetupStateUpdate(
                                    requires_setup=state.requires_setup,
                                    setup_complete=False,
                                    setup_status="degraded",
                                    broker_mode=state.broker_mode,
                                    direct_mqtt_supported=state.direct_mqtt_supported,
                                    setup_error=(status.degraded_reason or "runtime_unhealthy"),
                                    authority_mode=state.authority_mode,
                                    authority_ready=False,
                                )
                            )
                            if audit is not None:
                                await audit.append_event(
                                    event_type="mqtt_runtime_health",
                                    status="degraded",
                                    message=status.degraded_reason,
                                    payload={"provider": status.provider, "state": status.state},
                                )
                        elif state.setup_status == "degraded" and state.setup_error:
                            await state_store.update_setup_state(
                                MqttSetupStateUpdate(
                                    requires_setup=state.requires_setup,
                                    setup_complete=True,
                                    setup_status="ready",
                                    broker_mode=state.broker_mode,
                                    direct_mqtt_supported=state.direct_mqtt_supported,
                                    setup_error=None,
                                    authority_mode=state.authority_mode,
                                    authority_ready=True,
                                )
                            )
                        if status.healthy and startup_reconciler is not None:
                            # Keep bootstrap discovery fresh for listeners that join later.
                            await startup_reconciler.ensure_bootstrap_published(force=True)
                    if mqtt_manager is not None and mqtt_obsv is not None:
                        manager_status = await mqtt_manager.status()
                        denied_count = await mqtt_obsv.count_events(event_type="denied_topic_attempt")
                        await mqtt_obsv.append_event(
                            event_type="broker_health_telemetry",
                            source="mqtt_runtime_supervisor",
                            severity="info",
                            metadata={
                                "connected": bool(manager_status.get("connected")),
                                "connection_count": int(manager_status.get("connection_count") or 0),
                                "auth_failures": int(manager_status.get("auth_failures") or 0),
                                "reconnect_spikes": int(manager_status.get("reconnect_spikes") or 0),
                                "denied_topic_attempts": int(denied_count),
                            },
                        )
                    if noisy_evaluator is not None:
                        await noisy_evaluator.evaluate()
                except Exception:
                    log.exception("MQTT runtime supervision loop failed")
                await asyncio.sleep(30.0)

        asyncio.create_task(mqtt_runtime_supervision_loop())

    @app.on_event("shutdown")
    async def shutdown_background_tasks():
        proxy = getattr(app.state, "addon_proxy", None)
        if proxy is not None:
            await proxy.aclose()
        mqtt_manager = getattr(app.state, "mqtt_manager", None)
        if mqtt_manager is not None:
            await mqtt_manager.stop()
        mqtt_runtime_boundary = getattr(app.state, "mqtt_runtime_boundary", None)
        if mqtt_runtime_boundary is not None:
            stop = getattr(mqtt_runtime_boundary, "stop", None)
            if callable(stop):
                await stop()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost",
            "http://127.0.0.1",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
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
    mqtt_observability_db = os.getenv(
        "MQTT_OBSERVABILITY_DB",
        os.path.join(os.getcwd(), "var", "mqtt_observability.db"),
    )
    mqtt_observability_store = MqttObservabilityStore(mqtt_observability_db)
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
    app.state.mqtt_observability_store = mqtt_observability_store
    app.state.policy_store = policy_store
    app.state.telemetry_store = telemetry_store
    app.state.audit_store = audit_store
    app.state.store_audit_store = store_audit_store
    app.state.store_sources_store = store_sources_store
    app.state.users_store = users_store
    install_sessions_store = InstallSessionsStore()
    node_onboarding_sessions_store = NodeOnboardingSessionsStore()
    node_registrations_store = NodeRegistrationsStore()
    node_trust_store = NodeTrustStore()
    node_trust_issuance = NodeTrustIssuanceService(node_trust_store)
    node_capability_profiles_store = NodeCapabilityProfilesStore()
    provider_model_policy_store = ProviderModelPolicyStore()
    provider_model_policy_service = ProviderModelApprovalPolicyService(provider_model_policy_store)
    model_routing_registry_store = ModelRoutingRegistryStore()
    model_routing_registry_service = ModelRoutingRegistryService(model_routing_registry_store)
    node_capability_acceptance = NodeCapabilityAcceptanceService(
        node_capability_profiles_store,
        provider_model_policy=provider_model_policy_service,
    )
    node_governance_store = NodeGovernanceStore()
    node_governance_service = NodeGovernanceService(node_governance_store)
    node_governance_status_store = NodeGovernanceStatusStore()
    node_governance_status_service = NodeGovernanceStatusService(node_governance_status_store)
    node_telemetry_store = NodeTelemetryStore()
    node_telemetry_service = NodeTelemetryService(node_telemetry_store)
    app.state.install_sessions_store = install_sessions_store
    app.state.node_onboarding_sessions_store = node_onboarding_sessions_store
    app.state.node_registrations_store = node_registrations_store
    app.state.node_trust_store = node_trust_store
    app.state.node_trust_issuance = node_trust_issuance
    app.state.node_capability_profiles_store = node_capability_profiles_store
    app.state.node_capability_acceptance = node_capability_acceptance
    app.state.model_routing_registry_store = model_routing_registry_store
    app.state.model_routing_registry_service = model_routing_registry_service
    app.state.node_governance_store = node_governance_store
    app.state.node_governance_service = node_governance_service
    app.state.node_governance_status_store = node_governance_status_store
    app.state.node_governance_status_service = node_governance_status_service
    app.state.node_telemetry_store = node_telemetry_store
    app.state.node_telemetry_service = node_telemetry_service

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
        observability_store=mqtt_observability_store,
        enabled=bool(getattr(cfg_boot, "mqtt_listener_enabled", True)),
    )
    app.state.mqtt_manager = mqtt_manager
    app.state.notification_publisher = CoreNotificationPublisher(mqtt_manager)
    mqtt_dirs = ensure_runtime_dirs(os.getcwd())
    mqtt_live_dir = mqtt_dirs["live"]
    mqtt_credential_store = MqttCredentialStore(
        os.getenv("MQTT_CREDENTIAL_STORE_PATH", os.path.join(os.getcwd(), "var", "mqtt_credentials.json"))
    )
    runtime_provider = str(os.getenv("SYNTHIA_MQTT_RUNTIME_PROVIDER", "docker")).strip().lower()
    if runtime_provider in {"memory", "inmemory"}:
        mqtt_runtime_boundary = InMemoryBrokerRuntimeBoundary(provider="embedded_mosquitto")
    else:
        mqtt_runtime_boundary = DockerMosquittoRuntimeBoundary(
            live_dir=mqtt_live_dir,
            staged_dir=mqtt_dirs["staged"],
            data_dir=mqtt_dirs["data"],
            log_dir=mqtt_dirs["logs"],
            container_name=os.getenv("SYNTHIA_MQTT_DOCKER_CONTAINER", "synthia-mqtt-broker"),
            image=os.getenv("SYNTHIA_MQTT_DOCKER_IMAGE", "eclipse-mosquitto:2"),
            host=str(os.getenv("SYNTHIA_MQTT_HOST", "127.0.0.1")),
            port=int(os.getenv("SYNTHIA_MQTT_PORT", "1883")),
            bootstrap_port=int(os.getenv("SYNTHIA_MQTT_BOOTSTRAP_PORT", "1884")),
        )
    mqtt_acl_compiler = MqttAclCompiler()
    mqtt_config_renderer = MqttBrokerConfigRenderer()
    mqtt_apply_pipeline = MqttApplyPipeline(
        runtime_boundary=mqtt_runtime_boundary,
        audit_store=mqtt_authority_audit,
        live_dir=mqtt_live_dir,
        staged_dir=mqtt_dirs["staged"],
    )
    mqtt_startup_reconciler = EmbeddedMqttStartupReconciler(
        state_store=mqtt_integration_state_store,
        acl_compiler=mqtt_acl_compiler,
        config_renderer=mqtt_config_renderer,
        apply_pipeline=mqtt_apply_pipeline,
        audit_store=mqtt_authority_audit,
        credential_store=mqtt_credential_store,
        mqtt_manager=mqtt_manager,
    )
    mqtt_registration_approval = MqttRegistrationApprovalService(
        registry=registry,
        state_store=mqtt_integration_state_store,
        observability_store=mqtt_observability_store,
        runtime_reconcile_hook=mqtt_startup_reconciler.reconcile_authority,
        audit_store=mqtt_authority_audit,
        credential_rotate_hook=mqtt_credential_store.rotate_principal,
    )
    app.state.mqtt_registration_approval = mqtt_registration_approval
    app.state.mqtt_runtime_boundary = mqtt_runtime_boundary
    app.state.mqtt_credential_store = mqtt_credential_store
    app.state.mqtt_acl_compiler = mqtt_acl_compiler
    app.state.mqtt_config_renderer = mqtt_config_renderer
    app.state.mqtt_apply_pipeline = mqtt_apply_pipeline
    app.state.mqtt_startup_reconciler = mqtt_startup_reconciler
    mqtt_noisy_evaluator = MqttNoisyClientEvaluator(
        state_store=mqtt_integration_state_store,
        mqtt_manager=mqtt_manager,
        observability_store=mqtt_observability_store,
        audit_store=mqtt_authority_audit,
    )
    app.state.mqtt_noisy_evaluator = mqtt_noisy_evaluator
    register_addons(app, registry)
    addon_proxy = AddonProxy(registry)
    app.state.addon_proxy = addon_proxy

    # System API using the registry
    runtime_service = StandaloneRuntimeService()
    app.state.standalone_runtime_service = runtime_service
    app.include_router(
        build_system_router(
            registry,
            runtime_service,
            mqtt_registration_approval,
            mqtt_integration_state_store=mqtt_integration_state_store,
            mqtt_credential_store=mqtt_credential_store,
            mqtt_runtime_reconciler=mqtt_startup_reconciler,
            onboarding_sessions_store=node_onboarding_sessions_store,
            node_registrations_store=node_registrations_store,
            node_trust_issuance=node_trust_issuance,
            node_capability_acceptance=node_capability_acceptance,
            node_governance_service=node_governance_service,
            node_governance_status_service=node_governance_status_service,
            node_telemetry_service=node_telemetry_service,
            provider_model_policy_service=provider_model_policy_service,
            model_routing_registry_service=model_routing_registry_service,
            audit_store=audit_store,
        ),
        prefix="/api",
    )
    app.include_router(build_addons_registry_router(registry), prefix="/api")
    app.include_router(build_addons_install_router(registry, install_sessions_store), prefix="/api")
    app.include_router(build_admin_registry_router(registry, mqtt_registration_approval), prefix="/api")
    app.include_router(
        build_mqtt_router(
            mqtt_manager,
            registry,
            mqtt_integration_state_store,
            service_token_keys,
            settings_store=settings_store,
            approval_service=mqtt_registration_approval,
            acl_compiler=mqtt_acl_compiler,
            credential_store=mqtt_credential_store,
            runtime_reconciler=mqtt_startup_reconciler,
            runtime_boundary=mqtt_runtime_boundary,
            observability_store=mqtt_observability_store,
            audit_store=mqtt_authority_audit,
            node_registrations_store=node_registrations_store,
        ),
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

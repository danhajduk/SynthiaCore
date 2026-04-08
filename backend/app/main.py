# /backend/app/main.py
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
import subprocess
from datetime import timedelta
from pathlib import Path
import httpx

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core import (
    CoreNotificationPublisher,
    CoreStartupNotificationProducer,
    CoreSystemNotificationService,
    DevelopmentNotificationTrigger,
    LocalDesktopNotificationConsumer,
    NodeOperationalNotificationService,
    NotificationBridgeService,
    NodeNotificationProxyService,
)
from .core.logging import setup_logging
from .core.health import router as health_router
from .architecture import build_architecture_router
from .edge import EdgeGatewayService, EdgeGatewayStore, build_edge_router
from .addons.registry import build_registry, list_addons, register_addons
from .addons.install_sessions import InstallSessionsStore
from .addons.proxy import AddonProxy, build_proxy_router
from .nodes import NodeUiProxy, build_node_ui_proxy_router, build_nodes_router, NodesDomainService
from .supervisor.client import SupervisorApiClient
from .supervisor.runtime_store import SupervisorRuntimeNodesStore
from .api.system import build_system_router
from .api.admin_registry import build_admin_registry_router
from .api.addons_registry import build_addons_registry_router
from .api.addons_install import build_addons_install_router
from .proxy_routes import ProxyRouteRedirectMiddleware
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
from app.system.internal_scheduler_router import build_internal_scheduler_router
from app.system.settings.store import SettingsStore
from app.system.settings.router import build_settings_router
from app.system.platform_identity import default_platform_naming
from app.system.onboarding import (
    ModelRoutingRegistryService,
    ModelRoutingRegistryStore,
    NodeBudgetService,
    NodeBudgetStore,
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
from app.system.supervisor_status import build_supervisor_status_router
from app.system.internal_scheduler import InternalScheduler
from app.system.internal_scheduler_state_store import InternalSchedulerStateStore
from app.store import CatalogCacheClient, build_store_models_router, StoreAuditLogStore, StoreSourcesStore, build_store_router
from app.store.catalog import catalog_refresh_due

setup_logging()
log = logging.getLogger("synthia.core")


def create_app() -> FastAPI:
    naming = default_platform_naming()
    app = FastAPI(
        title=naming.core(),
        description=f"{naming.core()} is the control-plane service for {naming.platform()}.",
        version="0.1.0",
    )
    log.info("Starting %s", naming.core())
    cfg_boot = load_config()

    api_metrics = ApiMetricsCollector()
    app.state.api_metrics = api_metrics

    app.add_middleware(
        ApiMetricsMiddleware,
        collector=api_metrics,
        trust_proxy_headers=False,
    )
    app.add_middleware(ProxyRouteRedirectMiddleware)

    @app.on_event("startup")
    async def start_background_tasks():
        log.info("Starting background tasks for stats sampling and API metrics")
        cfg = load_config()
        app.state.system_config = cfg
        app.state.latest_stats = None
        app.state.latest_api_metrics = None
        app.state.latest_system_snapshot = None
        app.state.startup_warmup_tasks = []

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

        def _load_core_runtime_overrides() -> list[dict[str, object]]:
            raw = str(os.getenv("HEXE_CORE_RUNTIME_DECLARATIONS_JSON", "")).strip()
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
            except Exception:
                log.warning("Invalid HEXE_CORE_RUNTIME_DECLARATIONS_JSON payload")
                return []
            if isinstance(parsed, dict):
                items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
            elif isinstance(parsed, list):
                items = parsed
            else:
                items = []
            return [item for item in items if isinstance(item, dict)]

        async def _probe_core_api_health() -> tuple[str, str | None]:
            host = str(os.getenv("SYNTHIA_BACKEND_HOST", "127.0.0.1")).strip() or "127.0.0.1"
            port = str(os.getenv("SYNTHIA_BACKEND_PORT", "9001")).strip() or "9001"
            url = f"http://{host}:{port}/api/health"
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    response = await client.get(url)
                if response.status_code != 200:
                    return "unhealthy", f"http_{response.status_code}"
                payload = response.json()
                status = str(payload.get("status") or "ok").strip().lower()
                return ("healthy", None) if status == "ok" else ("unhealthy", f"status_{status}")
            except Exception as exc:
                return "unhealthy", str(exc)

        def _docker_stats_sync(container_names: list[str]) -> dict[str, dict[str, float]]:
            if not container_names:
                return {}
            names = [str(name).strip() for name in container_names if str(name).strip()]
            if not names:
                return {}
            try:
                result = subprocess.run(
                    [
                        "docker",
                        "stats",
                        "--no-stream",
                        "--format",
                        "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}",
                        *names,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    check=False,
                )
            except Exception:
                return {}
            if result.returncode != 0:
                return {}
            stats: dict[str, dict[str, float]] = {}
            for line in (result.stdout or "").splitlines():
                parts = [chunk.strip() for chunk in line.split("\t")]
                if len(parts) < 3:
                    continue
                name, cpu_raw, mem_raw = parts[0], parts[1], parts[2]
                if not name:
                    continue
                try:
                    cpu = float(cpu_raw.replace("%", "").strip())
                except Exception:
                    cpu = 0.0
                try:
                    mem = float(mem_raw.replace("%", "").strip())
                except Exception:
                    mem = 0.0
                stats[name] = {"cpu_percent": cpu, "mem_percent": mem}
            return stats

        async def _collect_container_stats(container_names: list[str]) -> dict[str, dict[str, float]]:
            cache = getattr(app.state, "docker_stats_cache", None)
            if not isinstance(cache, dict):
                cache = {"ts": 0.0, "payload": {}}
                setattr(app.state, "docker_stats_cache", cache)
            ttl_s = 10.0
            raw_ttl = str(os.getenv("HEXE_SUPERVISOR_CONTAINER_STATS_CACHE_S", "")).strip()
            if raw_ttl:
                try:
                    ttl_s = max(1.0, float(raw_ttl))
                except Exception:
                    ttl_s = 10.0
            now = time.time()
            if cache.get("payload") and (now - float(cache.get("ts", 0.0))) <= ttl_s:
                return dict(cache["payload"])
            payload = await asyncio.to_thread(_docker_stats_sync, container_names)
            cache["payload"] = payload
            cache["ts"] = now
            return dict(payload)

        async def _collect_core_aux_runtimes() -> list[dict[str, object]]:
            items: list[dict[str, object]] = []
            hostname = socket.gethostname()
            edge_store = getattr(app.state, "edge_gateway_store", None)
            if edge_store is None:
                return items
            try:
                cloudflare_settings = await edge_store.get_cloudflare_settings()
                tunnel_status = await edge_store.get_tunnel_status()
            except Exception:
                log.exception("Failed to load Cloudflare runtime state for Supervisor registration")
                return items

            if not cloudflare_settings.enabled and not tunnel_status.configured:
                return items

            runtime_state = str(tunnel_status.runtime_state or "unknown")
            desired_state = "running" if cloudflare_settings.enabled else "stopped"
            lifecycle_state = runtime_state if runtime_state and runtime_state != "unknown" else desired_state
            running = runtime_state.lower() in {"running", "active", "connected"} or bool(tunnel_status.healthy)
            health_status = "healthy" if tunnel_status.healthy else ("unhealthy" if cloudflare_settings.enabled else "unknown")
            last_error = tunnel_status.last_error or cloudflare_settings.last_provision_error
            provider = str(os.getenv("SYNTHIA_CLOUDFLARED_PROVIDER", "auto")).strip().lower() or "auto"
            container_name = (
                str(os.getenv("SYNTHIA_CLOUDFLARED_CONTAINER_NAME", "hexe-cloudflared")).strip() or "hexe-cloudflared"
            ) if provider == "docker" else None
            stats = await _collect_container_stats([container_name] if container_name else [])
            runtime_usage = stats.get(container_name or "", {}) if container_name else {}

            provisioning_state = getattr(cloudflare_settings.provisioning_state, "value", cloudflare_settings.provisioning_state)
            items.append(
                {
                    "runtime_id": "cloudflared",
                    "runtime_name": "Cloudflared",
                    "runtime_kind": "aux_container",
                    "management_mode": "manage",
                    "host_id": hostname,
                    "hostname": hostname,
                    "desired_state": desired_state,
                    "runtime_state": runtime_state,
                    "lifecycle_state": lifecycle_state,
                    "health_status": health_status,
                    "last_error": last_error,
                    "running": running,
                    "resource_usage": runtime_usage,
                    "runtime_metadata": {
                        "component": "cloudflared",
                        "provider": provider,
                        "enabled": cloudflare_settings.enabled,
                        "configured": tunnel_status.configured,
                        "tunnel_id": cloudflare_settings.tunnel_id or tunnel_status.tunnel_id,
                        "tunnel_name": cloudflare_settings.tunnel_name or tunnel_status.tunnel_name,
                        "config_path": tunnel_status.config_path,
                        "provisioning_state": str(provisioning_state),
                        "last_provisioned_at": cloudflare_settings.last_provisioned_at,
                        "container_name": container_name,
                    },
                }
            )
            return items

        async def _collect_core_addon_runtimes() -> list[dict[str, object]]:
            registry = getattr(app.state, "addon_registry", None)
            if registry is None:
                return []
            hostname = socket.gethostname()
            addons = list_addons(registry)
            mqtt_runtime = getattr(app.state, "mqtt_runtime_boundary", None)
            mqtt_status = None
            if mqtt_runtime is not None:
                status_fn = getattr(mqtt_runtime, "get_status", None)
                if callable(status_fn):
                    try:
                        mqtt_status = await status_fn()
                    except Exception:
                        log.exception("Failed to load MQTT runtime status for Supervisor registration")

            container_names: list[str] = []
            mqtt_container_name = str(os.getenv("SYNTHIA_MQTT_DOCKER_CONTAINER", "synthia-mqtt-broker"))
            container_names.append(mqtt_container_name)
            for addon in addons:
                last_health = addon.get("last_health") if isinstance(addon.get("last_health"), dict) else {}
                raw_containers = last_health.get("containers") if isinstance(last_health, dict) else None
                if isinstance(raw_containers, list):
                    for container in raw_containers:
                        if isinstance(container, dict):
                            name = str(container.get("name") or container.get("container_name") or "").strip()
                            if name:
                                container_names.append(name)
            container_stats = await _collect_container_stats(container_names)

            items: list[dict[str, object]] = []
            for addon in addons:
                addon_id = str(addon.get("id") or "").strip()
                if not addon_id:
                    continue
                health_status = str(addon.get("health_status") or "unknown")
                enabled = bool(addon.get("enabled", True))
                last_health = addon.get("last_health") if isinstance(addon.get("last_health"), dict) else {}
                containers: list[dict[str, object]] = []
                raw_containers = last_health.get("containers") if isinstance(last_health, dict) else None
                if isinstance(raw_containers, list):
                    containers = [item for item in raw_containers if isinstance(item, dict)]
                if addon_id == "mqtt" and not containers and mqtt_status is not None:
                    container_name = mqtt_container_name
                    stats = container_stats.get(container_name, {})
                    containers = [
                        {
                            "name": container_name,
                            "status": str(getattr(mqtt_status, "state", "unknown")),
                            "healthy": bool(getattr(mqtt_status, "healthy", False)),
                            "provider": str(getattr(mqtt_status, "provider", "unknown")),
                            "degraded_reason": getattr(mqtt_status, "degraded_reason", None),
                            "cpu_percent": stats.get("cpu_percent"),
                            "mem_percent": stats.get("mem_percent"),
                        }
                    ]
                for container in containers:
                    name = str(container.get("name") or container.get("container_name") or "").strip()
                    stats = container_stats.get(name, {})
                    if stats:
                        container.setdefault("cpu_percent", stats.get("cpu_percent"))
                        container.setdefault("mem_percent", stats.get("mem_percent"))
                running = health_status in {"ok", "healthy"}
                if addon_id == "mqtt" and mqtt_status is not None:
                    running = bool(getattr(mqtt_status, "healthy", False))
                    health_status = "healthy" if running else "unhealthy"
                primary_container = containers[0] if containers else {}
                runtime_usage = {
                    "cpu_percent": primary_container.get("cpu_percent"),
                    "mem_percent": primary_container.get("mem_percent"),
                } if containers else {}
                items.append(
                    {
                        "runtime_id": f"addon:{addon_id}",
                        "runtime_name": str(addon.get("name") or addon_id),
                        "runtime_kind": "addon",
                        "management_mode": "manage",
                        "host_id": hostname,
                        "hostname": hostname,
                        "desired_state": "running" if enabled else "stopped",
                        "runtime_state": "running" if running else "unknown",
                        "lifecycle_state": "running" if running else "unknown",
                        "health_status": health_status,
                        "running": running,
                        "resource_usage": runtime_usage,
                        "runtime_metadata": {
                            "addon_id": addon_id,
                            "version": addon.get("version"),
                            "base_url": addon.get("base_url"),
                            "ui_base_url": addon.get("ui_base_url"),
                            "ui_mode": addon.get("ui_mode"),
                            "platform_managed": addon.get("platform_managed"),
                            "containers": containers,
                            "container_count": len(containers),
                        },
                    }
                )
            return items

        async def _collect_core_runtime_declarations(
            *,
            core_health_status: str,
            core_last_error: str | None,
        ) -> list[dict[str, object]]:
            hostname = socket.gethostname()
            items: list[dict[str, object]] = [
                {
                    "runtime_id": "core-api",
                    "runtime_name": f"{naming.core()} API",
                    "runtime_kind": "core_service",
                    "management_mode": "monitor",
                    "host_id": hostname,
                    "hostname": hostname,
                    "desired_state": "running",
                    "runtime_state": "running" if core_health_status == "healthy" else "error",
                    "lifecycle_state": "running",
                    "health_status": core_health_status,
                    "last_error": core_last_error,
                    "running": True,
                    "runtime_metadata": {"component": "core-api"},
                }
            ]
            items.extend(await _collect_core_addon_runtimes())
            items.extend(await _collect_core_aux_runtimes())
            items.extend(_load_core_runtime_overrides())
            merged: dict[str, dict[str, object]] = {}
            for item in items:
                runtime_id = str(item.get("runtime_id") or "").strip()
                if not runtime_id:
                    continue
                runtime_kind = str(item.get("runtime_kind") or "core_service").strip().lower() or "core_service"
                if runtime_kind == "core_service":
                    item["management_mode"] = "monitor"
                item["runtime_kind"] = runtime_kind
                item.setdefault("host_id", hostname)
                item.setdefault("hostname", hostname)
                merged[runtime_id] = item
            return list(merged.values())

        async def core_runtime_supervisor_job_once() -> dict[str, object]:
            supervisor_client = getattr(app.state, "supervisor_client", None)
            if supervisor_client is None:
                raise ValueError("supervisor_client_unavailable")
            health_status, last_error = await _probe_core_api_health()
            payloads = await _collect_core_runtime_declarations(
                core_health_status=health_status,
                core_last_error=last_error,
            )
            sent = 0
            for payload in payloads:
                await asyncio.to_thread(supervisor_client.register_core_runtime, payload)
                heartbeat_payload = {
                    "runtime_id": payload.get("runtime_id"),
                    "host_id": payload.get("host_id"),
                    "hostname": payload.get("hostname"),
                    "runtime_state": payload.get("runtime_state"),
                    "lifecycle_state": payload.get("lifecycle_state"),
                    "health_status": payload.get("health_status"),
                    "last_error": payload.get("last_error"),
                    "running": payload.get("running"),
                    "resource_usage": payload.get("resource_usage", {}),
                    "runtime_metadata": payload.get("runtime_metadata", {}),
                }
                await asyncio.to_thread(supervisor_client.heartbeat_core_runtime, heartbeat_payload)
                sent += 1
            return {"status": "ok", "runtime_count": sent}

        internal_scheduler = getattr(app.state, "internal_scheduler", None)
        if internal_scheduler is not None and hasattr(internal_scheduler, "register_interval_task"):
            interval_seconds = 5
            raw_interval = str(os.getenv("HEXE_SUPERVISOR_CORE_HEARTBEAT_S", "")).strip()
            if raw_interval:
                try:
                    interval_seconds = max(1, int(float(raw_interval)))
                except Exception:
                    interval_seconds = 5
            schedule_name = "heartbeat_5_seconds" if interval_seconds == 5 else "interval_seconds"
            schedule_detail = None if interval_seconds == 5 else f"Every {interval_seconds} seconds"
            internal_scheduler.register_interval_task(
                task_id="core_runtime_heartbeat",
                display_name="Core Runtime Heartbeat",
                interval_seconds=interval_seconds,
                schedule_name=schedule_name,
                schedule_detail=schedule_detail,
                task_kind="local_recurring",
                readiness_critical=False,
            )
            internal_scheduler.start_interval_task(
                task_id="core_runtime_heartbeat",
                coroutine_factory=core_runtime_supervisor_job_once,
                initial_delay_seconds=1,
            )

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
        async def mqtt_warmup_sequence() -> None:
            mqtt_manager = getattr(app.state, "mqtt_manager", None)
            if mqtt_manager is not None:
                await mqtt_manager.start()
                connected = await mqtt_manager.wait_until_connected(timeout_s=10.0)
                if not connected:
                    log.warning("MQTT manager did not report connected before startup notification phase")
            notification_bridge = getattr(app.state, "notification_bridge", None)
            if notification_bridge is not None:
                await notification_bridge.start()
            notification_consumer = getattr(app.state, "notification_consumer", None)
            if notification_consumer is not None:
                await notification_consumer.start()
            notification_proxy = getattr(app.state, "notification_proxy", None)
            if notification_proxy is not None:
                await notification_proxy.start()
            mqtt_startup_reconciler = getattr(app.state, "mqtt_startup_reconciler", None)
            if mqtt_startup_reconciler is not None:
                try:
                    await mqtt_startup_reconciler.reconcile_startup()
                    if mqtt_manager is not None:
                        await mqtt_manager.restart()
                        connected = await mqtt_manager.wait_until_connected(timeout_s=10.0)
                        if not connected:
                            log.warning("MQTT manager did not reconnect before post-reconcile startup notifications")
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
            notification_producer = getattr(app.state, "notification_producer", None)
            if notification_producer is not None:
                try:
                    await notification_producer.emit_startup_notifications()
                except Exception:
                    log.exception("Core startup notification emission failed")
            system_notification_service = getattr(app.state, "system_notification_service", None)
            if system_notification_service is not None:
                try:
                    await system_notification_service.emit_system_online(
                        component="startup",
                        message=f"{naming.core()} startup completed and the {naming.core()} is now online.",
                    )
                except Exception:
                    log.exception("Core HA system online notification emission failed")

        def _track_startup_task(task: asyncio.Task) -> None:
            tasks = getattr(app.state, "startup_warmup_tasks", None)
            if isinstance(tasks, list):
                tasks.append(task)

            def _finalize(done: asyncio.Task) -> None:
                running = getattr(app.state, "startup_warmup_tasks", None)
                if isinstance(running, list) and done in running:
                    running.remove(done)
                if done.cancelled():
                    return
                exc = done.exception()
                if exc is not None:
                    log.exception("Startup warmup task failed", exc_info=exc)

            task.add_done_callback(_finalize)

        _track_startup_task(asyncio.create_task(mqtt_warmup_sequence()))

        async def node_operational_notification_loop() -> None:
            while True:
                try:
                    service = getattr(app.state, "node_operational_notification_service", None)
                    if service is not None:
                        await service.poll_once()
                except Exception:
                    log.exception("Node operational notification loop failed")
                await asyncio.sleep(30.0)

        asyncio.create_task(node_operational_notification_loop())

        async def mqtt_runtime_supervision_loop() -> None:
            last_runtime_healthy: bool | None = None
            last_runtime_warning_reason: str | None = None
            last_runtime_error_reason: str | None = None
            while True:
                try:
                    runtime = getattr(app.state, "mqtt_runtime_boundary", None)
                    state_store = getattr(app.state, "mqtt_integration_state_store", None)
                    audit = getattr(app.state, "mqtt_authority_audit", None)
                    mqtt_manager = getattr(app.state, "mqtt_manager", None)
                    mqtt_obsv = getattr(app.state, "mqtt_observability_store", None)
                    startup_reconciler = getattr(app.state, "mqtt_startup_reconciler", None)
                    noisy_evaluator = getattr(app.state, "mqtt_noisy_evaluator", None)
                    system_notification_service = getattr(app.state, "system_notification_service", None)
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
                            degraded_reason = str(status.degraded_reason or "runtime_unhealthy").strip() or "runtime_unhealthy"
                            if (
                                system_notification_service is not None
                                and (
                                    last_runtime_healthy is not False
                                    or last_runtime_warning_reason != degraded_reason
                                )
                            ):
                                await system_notification_service.emit_system_warning(
                                    component="mqtt_runtime",
                                    message=f"{naming.core()} MQTT runtime warning: {degraded_reason}",
                                    dedupe_key="core-mqtt-runtime-warning",
                                    data={
                                        "provider": status.provider,
                                        "state": status.state,
                                        "degraded_reason": degraded_reason,
                                    },
                                )
                            last_runtime_healthy = False
                            last_runtime_warning_reason = degraded_reason
                            last_runtime_error_reason = None
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
                        if status.healthy:
                            if (
                                system_notification_service is not None
                                and (
                                    last_runtime_healthy is False
                                    or last_runtime_error_reason is not None
                                )
                            ):
                                await system_notification_service.emit_system_online(
                                    component="mqtt_runtime",
                                    message=f"{naming.core()} MQTT runtime is healthy again.",
                                )
                            last_runtime_healthy = True
                            last_runtime_warning_reason = None
                            last_runtime_error_reason = None
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
                except Exception as exc:
                    log.exception("MQTT runtime supervision loop failed")
                    system_notification_service = getattr(app.state, "system_notification_service", None)
                    error_reason = f"{type(exc).__name__}:{str(exc or '').strip()}"
                    if (
                        system_notification_service is not None
                        and last_runtime_error_reason != error_reason
                    ):
                        message = f"{naming.core()} MQTT runtime supervision error: {type(exc).__name__}"
                        detail = str(exc or "").strip()
                        if detail:
                            message = f"{message}: {detail}"
                        try:
                            await system_notification_service.emit_system_error(
                                component="mqtt_runtime_supervisor",
                                message=message,
                                dedupe_key="core-mqtt-runtime-error",
                                data={"error_type": type(exc).__name__, "error": detail or None},
                            )
                        except Exception:
                            log.exception("Core HA system error notification emission failed")
                    last_runtime_healthy = False
                    last_runtime_error_reason = error_reason
                await asyncio.sleep(30.0)

        asyncio.create_task(mqtt_runtime_supervision_loop())

    @app.on_event("shutdown")
    async def shutdown_background_tasks():
        for task in list(getattr(app.state, "startup_warmup_tasks", []) or []):
            task.cancel()
        proxy = getattr(app.state, "addon_proxy", None)
        if proxy is not None:
            await proxy.aclose()
        mqtt_manager = getattr(app.state, "mqtt_manager", None)
        if mqtt_manager is not None:
            await mqtt_manager.stop()
        notification_bridge = getattr(app.state, "notification_bridge", None)
        if notification_bridge is not None:
            await notification_bridge.stop()
        notification_consumer = getattr(app.state, "notification_consumer", None)
        if notification_consumer is not None:
            await notification_consumer.stop()
        notification_proxy = getattr(app.state, "notification_proxy", None)
        if notification_proxy is not None:
            await notification_proxy.stop()
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
    edge_gateway_db = os.getenv(
        "EDGE_GATEWAY_DB",
        os.path.join(os.getcwd(), "var", "edge_gateway.json"),
    )
    edge_gateway_store = EdgeGatewayStore(edge_gateway_db)
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

    app.state.settings_store = settings_store
    app.state.service_token_keys = service_token_keys
    app.state.service_catalog_store = service_catalog_store
    app.state.edge_gateway_store = edge_gateway_store
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
    node_budget_store = NodeBudgetStore()
    node_budget_service = NodeBudgetService(node_budget_store, model_routing_registry_service)
    node_governance_store = NodeGovernanceStore()
    node_governance_service = NodeGovernanceService(
        node_governance_store,
        provider_model_policy=provider_model_policy_service,
        node_budget_service=node_budget_service,
    )
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
    app.state.node_budget_store = node_budget_store
    app.state.node_budget_service = node_budget_service

    internal_scheduler_state_store = InternalSchedulerStateStore(
        path=os.path.join(os.getcwd(), "var", "internal_scheduler_state.json"),
        logger=log,
    )
    internal_scheduler = InternalScheduler(logger=log, store=internal_scheduler_state_store)
    app.state.internal_scheduler_state_store = internal_scheduler_state_store
    app.state.internal_scheduler = internal_scheduler

    app.include_router(build_settings_router(settings_store, audit_store), prefix="/api/system", tags=["settings"])
    app.include_router(build_users_router(users_store, audit_store), prefix="/api/admin", tags=["admin-users"])
    app.include_router(repo_status_router, prefix="/api/system", tags=["repo"])
    app.include_router(build_stack_health_router(), prefix="/api/system", tags=["stack-health"])
    app.include_router(build_supervisor_status_router(), prefix="/api/system", tags=["supervisor"])
    app.include_router(build_internal_scheduler_router(), prefix="/api/system", tags=["scheduler"])

    event_service = PlatformEventService()
    app.state.platform_events = event_service
    runtime_service = StandaloneRuntimeService()
    app.state.standalone_runtime_service = runtime_service
    supervisor_client = SupervisorApiClient()
    app.state.supervisor_client = supervisor_client
    supervisor_runtime_nodes_store = SupervisorRuntimeNodesStore()
    app.state.supervisor_runtime_nodes_store = supervisor_runtime_nodes_store
    edge_gateway_service = EdgeGatewayService(
        edge_gateway_store,
        settings_store=settings_store,
        node_registrations_store=node_registrations_store,
        supervisor_client=supervisor_client,
        audit_store=audit_store,
    )
    app.state.edge_gateway_service = edge_gateway_service

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
    app.state.notification_bridge = NotificationBridgeService(mqtt_manager, mqtt_manager)
    app.state.notification_consumer = LocalDesktopNotificationConsumer(mqtt_manager)
    app.state.notification_proxy = NodeNotificationProxyService(
        app.state.notification_publisher,
        mqtt_manager,
        mqtt_integration_state_store,
    )
    app.state.notification_producer = CoreStartupNotificationProducer(
        app.state.notification_publisher,
        core_version=app.version,
    )
    app.state.notification_debug_trigger = DevelopmentNotificationTrigger(
        app.state.notification_publisher,
        core_version=app.version,
    )
    app.state.system_notification_service = CoreSystemNotificationService(
        app.state.notification_publisher,
        core_version=app.version,
    )
    app.state.node_operational_notification_service = NodeOperationalNotificationService(
        app.state.notification_publisher,
        mqtt_manager,
        node_registrations_store,
        node_governance_status_service,
    )
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
    app.include_router(build_architecture_router(), prefix="/api")
    nodes_service = NodesDomainService(
        node_registrations_store,
        node_governance_status_service,
        supervisor_runtime_nodes_store,
        runtime_client=supervisor_client,
    )
    app.include_router(
        build_nodes_router(nodes_service),
        prefix="/api",
    )
    app.state.node_ui_proxy = NodeUiProxy(nodes_service)
    app.include_router(
        build_edge_router(edge_gateway_service),
        prefix="/api",
    )
    app.include_router(
        build_system_router(
            registry,
            runtime_service,
            mqtt_manager=mqtt_manager,
            service_token_key_store=service_token_keys,
            service_catalog_store=service_catalog_store,
            mqtt_approval_service=mqtt_registration_approval,
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
            node_budget_service=node_budget_service,
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
    app.include_router(build_node_ui_proxy_router(app.state.node_ui_proxy))

    return app


app = create_app()

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request


class _CachedSampler:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._connectivity_cache: dict[str, Any] | None = None
        self._speed_cache: dict[str, Any] | None = None

    async def connectivity(self) -> dict[str, Any]:
        now = time.time()
        ttl = float(os.getenv("SYNTHIA_STACK_CONNECTIVITY_TTL_S", "30") or 30)
        async with self._lock:
            if self._connectivity_cache and (now - float(self._connectivity_cache.get("ts", 0))) <= ttl:
                return dict(self._connectivity_cache["payload"])

            payload = await asyncio.to_thread(_sample_connectivity)
            self._connectivity_cache = {"ts": now, "payload": payload}
            return dict(payload)

    async def speed(self) -> dict[str, Any]:
        now = time.time()
        ttl = float(os.getenv("SYNTHIA_SPEEDTEST_SAMPLE_SECONDS", "1800") or 1800)
        async with self._lock:
            if self._speed_cache and (now - float(self._speed_cache.get("ts", 0))) <= ttl:
                cached = dict(self._speed_cache["payload"])
                sampled_at = cached.get("sampled_at")
                if sampled_at:
                    age = max(0, int(now - datetime.fromisoformat(str(sampled_at)).timestamp()))
                    cached["age_s"] = age
                return cached

            payload = await asyncio.to_thread(_sample_speed)
            self._speed_cache = {"ts": now, "payload": payload}
            return dict(payload)

    async def speed_cached(self) -> dict[str, Any]:
        now = time.time()
        async with self._lock:
            if not self._speed_cache:
                return {
                    "state": "unavailable",
                    "source": "speedtest_cli",
                    "download_mbps": None,
                    "upload_mbps": None,
                    "latency_ms": None,
                    "sampled_at": _now_iso(),
                    "age_s": 0,
                }
            cached = dict(self._speed_cache["payload"])
            sampled_at = cached.get("sampled_at")
            if sampled_at:
                age = max(0, int(now - datetime.fromisoformat(str(sampled_at)).timestamp()))
                cached["age_s"] = age
            return cached


async def speed_sampler_loop(interval_s: float | None = None) -> None:
    delay = interval_s
    if delay is None:
        delay = float(os.getenv("SYNTHIA_SPEEDTEST_SAMPLE_SECONDS", "1800") or 1800)
    delay = max(60.0, float(delay))
    while True:
        try:
            await _sampler.speed()
        except Exception:
            pass
        await asyncio.sleep(delay)


_sampler = _CachedSampler()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tcp_reachable(host: str, port: int, timeout_s: float = 1.5) -> bool:
    with socket.create_connection((host, port), timeout=timeout_s):
        return True


def _sample_connectivity() -> dict[str, Any]:
    local_host = str(os.getenv("SYNTHIA_LOCAL_NETWORK_CHECK_HOST", "")).strip()
    if not local_host:
        # Reuse MQTT host as a pragmatic local-network target when explicit
        # network health host is not configured.
        local_host = str(os.getenv("MQTT_HOST", "")).strip()
    local_port = int(str(os.getenv("SYNTHIA_LOCAL_NETWORK_CHECK_PORT", "53")).strip() or "53")
    if not local_host:
        # Backend service env commonly includes SYNTHIA_BACKEND_HOST/PORT.
        local_host = str(os.getenv("SYNTHIA_BACKEND_HOST", "")).strip()
        local_port = int(str(os.getenv("SYNTHIA_BACKEND_PORT", "9001")).strip() or "9001")
    internet_host = str(os.getenv("SYNTHIA_INTERNET_CHECK_HOST", "1.1.1.1")).strip()
    internet_port = int(str(os.getenv("SYNTHIA_INTERNET_CHECK_PORT", "53")).strip() or "53")

    network_state = "not_configured"
    if local_host:
        try:
            network_state = "reachable" if _tcp_reachable(local_host, local_port) else "unreachable"
        except OSError:
            network_state = "unreachable"
        except Exception:
            network_state = "unavailable"

    internet_state = "not_configured"
    if internet_host:
        try:
            internet_state = "reachable" if _tcp_reachable(internet_host, internet_port) else "unreachable"
        except OSError:
            internet_state = "unreachable"
        except Exception:
            internet_state = "unavailable"

    return {
        "network": {"state": network_state},
        "internet": {"state": internet_state},
    }


def _sample_speed() -> dict[str, Any]:
    sampled_at = _now_iso()
    timeout_s = float(str(os.getenv("SYNTHIA_SPEEDTEST_TIMEOUT_S", "45")).strip() or "45")
    cli_bin = str(os.getenv("SYNTHIA_SPEEDTEST_CLI_BIN", "speedtest-cli")).strip() or "speedtest-cli"
    commands: list[tuple[list[str], str]] = []
    seen: set[tuple[str, ...]] = set()

    def _add_command(cmd: list[str], source: str) -> None:
        key = tuple(str(x) for x in cmd)
        if not cmd or key in seen:
            return
        seen.add(key)
        commands.append((cmd, source))

    cli_parts = shlex.split(cli_bin)
    if cli_parts:
        if len(cli_parts) == 1:
            cmd_name = os.path.basename(cli_parts[0]).lower()
            if cmd_name == "speedtest":
                _add_command([cli_parts[0], "--accept-license", "--accept-gdpr", "--format=json"], "speedtest_ookla")
            else:
                _add_command([cli_parts[0], "--json", "--secure"], "speedtest_cli")
        else:
            cmd_name = os.path.basename(cli_parts[0]).lower()
            source = "speedtest_ookla" if cmd_name == "speedtest" else "speedtest_cli"
            _add_command(cli_parts, source)

    _add_command([sys.executable, "-m", "speedtest", "--json", "--secure"], "speedtest_cli")
    if shutil.which("speedtest"):
        _add_command(["speedtest", "--accept-license", "--accept-gdpr", "--format=json"], "speedtest_ookla")
    if shutil.which("speedtest-cli"):
        _add_command(["speedtest-cli", "--json", "--secure"], "speedtest_cli")

    for cmd, source in commands:
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(timeout_s, 1.0),
                check=False,
            )
            if completed.returncode != 0:
                continue
            payload = json.loads((completed.stdout or "").strip() or "{}")
            parsed = _parse_speed_payload(payload)
            if parsed is None:
                continue
            return {
                "state": "ok",
                "source": source,
                "download_mbps": parsed["download_mbps"],
                "upload_mbps": parsed["upload_mbps"],
                "latency_ms": parsed["latency_ms"],
                "sampled_at": sampled_at,
                "age_s": 0,
            }
        except Exception:
            continue

    return {
        "state": "unavailable",
        "source": "speedtest_cli",
        "download_mbps": None,
        "upload_mbps": None,
        "latency_ms": None,
        "sampled_at": sampled_at,
        "age_s": 0,
    }


def _parse_speed_payload(payload: dict[str, Any]) -> dict[str, float | None] | None:
    # speedtest-cli schema (download/upload in bits per second)
    if "download" in payload or "upload" in payload:
        try:
            download_bps = float(payload.get("download") or 0.0)
            upload_bps = float(payload.get("upload") or 0.0)
            latency_raw = payload.get("ping")
            latency_ms = round(float(latency_raw), 1) if latency_raw is not None else None
            return {
                "download_mbps": round(max(download_bps, 0.0) / 1_000_000.0, 2),
                "upload_mbps": round(max(upload_bps, 0.0) / 1_000_000.0, 2),
                "latency_ms": latency_ms,
            }
        except Exception:
            return None

    # Ookla schema (download/upload bandwidth in bytes per second)
    try:
        download = payload.get("download")
        upload = payload.get("upload")
        if isinstance(download, dict) and isinstance(upload, dict):
            down_bw = float(download.get("bandwidth") or 0.0)
            up_bw = float(upload.get("bandwidth") or 0.0)
            ping = payload.get("ping")
            latency_raw = ping.get("latency") if isinstance(ping, dict) else None
            latency_ms = round(float(latency_raw), 1) if latency_raw is not None else None
            return {
                "download_mbps": round(max(down_bw, 0.0) * 8.0 / 1_000_000.0, 2),
                "upload_mbps": round(max(up_bw, 0.0) * 8.0 / 1_000_000.0, 2),
                "latency_ms": latency_ms,
            }
    except Exception:
        return None
    return None


def _speed_from_throughput_fallback(throughput: dict[str, Any]) -> dict[str, Any] | None:
    if str(throughput.get("state") or "").strip().lower() != "ok":
        return None
    rx_bps = throughput.get("rx_Bps")
    tx_bps = throughput.get("tx_Bps")
    if not isinstance(rx_bps, (int, float)) or not isinstance(tx_bps, (int, float)):
        return None
    sampled_at = throughput.get("sampled_at") or _now_iso()
    return {
        "state": "ok",
        "source": "passive_estimate",
        "download_mbps": round(max(float(rx_bps), 0.0) * 8.0 / 1_000_000.0, 2),
        "upload_mbps": round(max(float(tx_bps), 0.0) * 8.0 / 1_000_000.0, 2),
        "latency_ms": None,
        "sampled_at": sampled_at,
        "age_s": 0,
    }


def _throughput_from_stats(stats: Any) -> dict[str, Any]:
    sampled_at = _now_iso()
    if stats is None:
        return {
            "state": "unavailable",
            "rx_Bps": None,
            "tx_Bps": None,
            "sampled_at": sampled_at,
        }

    net = getattr(stats, "net", None)
    total_rate = getattr(net, "total_rate", None) if net is not None else None
    if total_rate is None:
        return {
            "state": "warming_up",
            "rx_Bps": None,
            "tx_Bps": None,
            "sampled_at": sampled_at,
        }

    rx_bps = float(getattr(total_rate, "rx_Bps", 0.0) or 0.0)
    tx_bps = float(getattr(total_rate, "tx_Bps", 0.0) or 0.0)
    return {
        "state": "ok",
        "rx_Bps": round(max(rx_bps, 0.0), 2),
        "tx_Bps": round(max(tx_bps, 0.0), 2),
        "sampled_at": sampled_at,
    }


def _network_metrics_from_stats(stats: Any) -> dict[str, Any]:
    sampled_at = _now_iso()
    if stats is None:
        return {
            "state": "unavailable",
            "bytes_sent": None,
            "bytes_recv": None,
            "packets_sent": None,
            "packets_recv": None,
            "errin": None,
            "errout": None,
            "dropin": None,
            "dropout": None,
            "sampled_at": sampled_at,
        }
    net = getattr(stats, "net", None)
    total = getattr(net, "total", None) if net is not None else None
    if total is None:
        return {
            "state": "unavailable",
            "bytes_sent": None,
            "bytes_recv": None,
            "packets_sent": None,
            "packets_recv": None,
            "errin": None,
            "errout": None,
            "dropin": None,
            "dropout": None,
            "sampled_at": sampled_at,
        }
    return {
        "state": "ok",
        "bytes_sent": int(getattr(total, "bytes_sent", 0) or 0),
        "bytes_recv": int(getattr(total, "bytes_recv", 0) or 0),
        "packets_sent": int(getattr(total, "packets_sent", 0) or 0),
        "packets_recv": int(getattr(total, "packets_recv", 0) or 0),
        "errin": int(getattr(total, "errin", 0) or 0),
        "errout": int(getattr(total, "errout", 0) or 0),
        "dropin": int(getattr(total, "dropin", 0) or 0),
        "dropout": int(getattr(total, "dropout", 0) or 0),
        "sampled_at": sampled_at,
    }


def _state_from_bool(value: bool | None, healthy: str, unhealthy: str, unknown: str = "unknown") -> str:
    if value is None:
        return unknown
    return healthy if value else unhealthy


def _derive_overall_status(payload: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    non_degrading_reasons: set[str] = set()
    subsystems = payload.get("subsystems") or {}
    connectivity = payload.get("connectivity") or {}

    if subsystems.get("supervisor", {}).get("state") != "healthy":
        reasons.append("Supervisor unavailable")

    mqtt_state = subsystems.get("mqtt", {}).get("state")
    if mqtt_state == "disconnected":
        reasons.append("MQTT disconnected")
    mqtt_infra = subsystems.get("mqtt", {}).get("infrastructure", {})
    if isinstance(mqtt_infra, dict):
        broker_runtime = mqtt_infra.get("broker_runtime", {})
        if isinstance(broker_runtime, dict) and broker_runtime.get("healthy") is False:
            reasons.append("MQTT broker runtime unhealthy")
        authority = mqtt_infra.get("authority", {})
        if isinstance(authority, dict) and authority.get("healthy") is False:
            reasons.append("MQTT authority degraded")
        reconcile = mqtt_infra.get("reconciliation", {})
        if isinstance(reconcile, dict) and str(reconcile.get("status") or "").lower() in {"degraded", "error"}:
            broker_healthy = isinstance(broker_runtime, dict) and broker_runtime.get("healthy") is True
            authority_healthy = isinstance(authority, dict) and authority.get("healthy") is True
            setup_ready = isinstance(authority, dict) and authority.get("setup_ready") is True
            # Reconciliation status is historical. If runtime and authority have
            # already recovered, don't keep the whole dashboard degraded.
            if not (broker_healthy and authority_healthy and setup_ready):
                reasons.append("MQTT reconciliation degraded")
        bootstrap = mqtt_infra.get("bootstrap_publish", {})
        if (
            isinstance(bootstrap, dict)
            and bootstrap.get("published") is False
            and int(bootstrap.get("attempts") or 0) > 0
        ):
            reasons.append("MQTT bootstrap publish pending")

    scheduler_state = subsystems.get("scheduler", {}).get("state")
    if scheduler_state in {"degraded", "unknown"}:
        reasons.append("Scheduler unavailable")

    ai_state = str(subsystems.get("ai", {}).get("state") or "").strip().lower()
    if ai_state in {"offline", "disconnected"}:
        reasons.append("AI offline")

    worker_state = subsystems.get("workers", {}).get("state")
    if worker_state == "idle":
        reason = "No workers active"
        reasons.append(reason)
        non_degrading_reasons.add(reason)

    unhealthy_addons = int(subsystems.get("addons", {}).get("unhealthy_count") or 0)
    if unhealthy_addons > 0:
        reasons.append("Addon health issues detected")

    internet_state = connectivity.get("internet", {}).get("state")
    if internet_state in {"unreachable", "degraded"}:
        reasons.append("Internet unreachable")

    network_state = connectivity.get("network", {}).get("state")
    if network_state == "unreachable":
        reasons.append("Local network unreachable")

    overall = "ok"
    core_state = subsystems.get("core", {}).get("state")
    if core_state == "unknown":
        overall = "unknown"
    elif reasons:
        degrading_reasons = [reason for reason in reasons if reason not in non_degrading_reasons]
        if any(reason.startswith("Supervisor") for reason in reasons):
            overall = "attention"
        elif degrading_reasons:
            overall = "degraded"

    return {
        "overall": overall,
        "reasons": reasons,
        "updated_at": _now_iso(),
    }


def build_stack_health_router() -> APIRouter:
    router = APIRouter()

    @router.get("/stack/summary")
    async def stack_summary(request: Request):
        registry = getattr(request.app.state, "addon_registry", None)
        mqtt_manager = getattr(request.app.state, "mqtt_manager", None)
        mqtt_runtime_boundary = getattr(request.app.state, "mqtt_runtime_boundary", None)
        mqtt_state_store = getattr(request.app.state, "mqtt_integration_state_store", None)
        mqtt_startup_reconciler = getattr(request.app.state, "mqtt_startup_reconciler", None)
        scheduler_engine = getattr(request.app.state, "scheduler_engine", None)
        node_registrations_store = getattr(request.app.state, "node_registrations_store", None)

        core_state = "healthy"
        supervisor_running: bool | None = None
        stats = None
        try:
            stats = getattr(request.app.state, "latest_stats", None)
            services = stats.services if stats is not None else None
            if isinstance(services, dict):
                supervisor = services.get("supervisor")
                if supervisor is not None:
                    supervisor_running = bool(getattr(supervisor, "running", None))
        except Exception:
            supervisor_running = None

        mqtt_state = "unknown"
        mqtt_last_message_at = None
        mqtt_infrastructure = {
            "broker_runtime": {
                "healthy": None,
                "state": "unknown",
                "degraded_reason": None,
            },
            "authority": {
                "healthy": None,
                "setup_status": "unknown",
                "authority_ready": False,
                "setup_ready": False,
                "setup_error": None,
            },
            "reconciliation": {
                "status": "unknown",
                "last_reconcile_at": None,
                "last_reconcile_reason": None,
                "last_error": None,
                "last_runtime_state": "unknown",
            },
            "bootstrap_publish": {
                "published": False,
                "attempts": 0,
                "successes": 0,
                "last_attempt_at": None,
                "last_success_at": None,
                "last_error": None,
            },
        }
        if mqtt_manager is not None:
            try:
                mqtt_status = await mqtt_manager.status()
                connected = mqtt_status.get("connected")
                enabled = mqtt_status.get("enabled")
                if enabled is False:
                    mqtt_state = "unknown"
                else:
                    mqtt_state = _state_from_bool(
                        bool(connected) if connected is not None else None,
                        "connected",
                        "disconnected",
                    )
                mqtt_last_message_at = mqtt_status.get("last_message_at")
            except Exception:
                mqtt_state = "unknown"
        if mqtt_runtime_boundary is not None:
            try:
                runtime_status = await mqtt_runtime_boundary.get_status()
                mqtt_infrastructure["broker_runtime"] = {
                    "healthy": bool(runtime_status.healthy),
                    "state": str(runtime_status.state),
                    "degraded_reason": runtime_status.degraded_reason,
                }
            except Exception:
                pass
        if mqtt_state_store is not None:
            try:
                integration_state = await mqtt_state_store.get_state()
                setup_ready = bool(
                    (not integration_state.requires_setup)
                    or (
                        integration_state.setup_complete
                        and integration_state.setup_status == "ready"
                        and integration_state.authority_ready
                    )
                )
                mqtt_infrastructure["authority"] = {
                    "healthy": bool(integration_state.authority_ready and setup_ready),
                    "setup_status": integration_state.setup_status,
                    "authority_ready": bool(integration_state.authority_ready),
                    "setup_ready": setup_ready,
                    "setup_error": integration_state.setup_error,
                }
            except Exception:
                pass
        if mqtt_startup_reconciler is not None:
            try:
                reconcile_status = mqtt_startup_reconciler.reconciliation_status()
                bootstrap_status = mqtt_startup_reconciler.bootstrap_status()
                mqtt_infrastructure["reconciliation"] = {
                    "status": str(reconcile_status.get("last_reconcile_status") or "unknown"),
                    "last_reconcile_at": reconcile_status.get("last_reconcile_at"),
                    "last_reconcile_reason": reconcile_status.get("last_reconcile_reason"),
                    "last_error": reconcile_status.get("last_reconcile_error"),
                    "last_runtime_state": reconcile_status.get("last_runtime_state"),
                }
                mqtt_infrastructure["bootstrap_publish"] = {
                    "published": bool(bootstrap_status.get("published")),
                    "attempts": int(bootstrap_status.get("attempts") or 0),
                    "successes": int(bootstrap_status.get("successes") or 0),
                    "last_attempt_at": bootstrap_status.get("last_attempt_at"),
                    "last_success_at": bootstrap_status.get("last_success_at"),
                    "last_error": bootstrap_status.get("last_error"),
                }
            except Exception:
                pass

        scheduler_state = "unknown"
        active_leases = 0
        queued_jobs = 0
        if scheduler_engine is not None:
            try:
                snapshot = await scheduler_engine.snapshot()
                active_leases = int(getattr(snapshot, "active_leases", 0) or 0)
                q = getattr(snapshot, "queue_depths", {}) or {}
                queued_jobs = sum(int(v or 0) for v in q.values())
                if active_leases > 0:
                    scheduler_state = "running"
                elif queued_jobs > 0:
                    scheduler_state = "degraded"
                else:
                    scheduler_state = "idle"
            except Exception:
                scheduler_state = "unknown"

        installed_count = 0
        unhealthy_count = 0
        if registry is not None:
            try:
                ids: set[str] = set()
                addons = getattr(registry, "addons", {})
                if isinstance(addons, dict):
                    ids.update(str(x) for x in addons.keys())
                registered = getattr(registry, "registered", {})
                if isinstance(registered, dict):
                    ids.update(str(x) for x in registered.keys())

                for addon_id in sorted(ids):
                    enabled = True
                    if hasattr(registry, "is_enabled"):
                        try:
                            enabled = bool(registry.is_enabled(addon_id))
                        except Exception:
                            enabled = True
                    if not enabled:
                        continue
                    installed_count += 1
                    health_raw = None
                    if isinstance(registered, dict) and addon_id in registered:
                        health_raw = getattr(registered[addon_id], "health_status", None)
                    health = str(health_raw or "unknown").strip().lower()
                    if health in {"unhealthy", "error", "failed", "down"}:
                        unhealthy_count += 1
            except Exception:
                installed_count = 0
                unhealthy_count = 0

        connectivity = await _sampler.connectivity()
        throughput = _throughput_from_stats(stats)
        speed = await _sampler.speed_cached()
        if str(speed.get("state") or "").strip().lower() != "ok":
            passive_speed = _speed_from_throughput_fallback(throughput)
            if passive_speed is not None:
                speed = passive_speed
        network_metrics = _network_metrics_from_stats(stats)

        ai_total_nodes = 0
        ai_trusted_nodes = 0
        ai_state = "unknown"
        if node_registrations_store is not None:
            try:
                registrations = list(node_registrations_store.list())
                ai_nodes = []
                for item in registrations:
                    node_type = str(getattr(item, "node_type", "") or "").strip().lower()
                    # Accept legacy "ai" and canonical "ai-node" labels.
                    if node_type in {"ai", "ai-node"}:
                        ai_nodes.append(item)
                ai_total_nodes = len(ai_nodes)
                ai_trusted_nodes = sum(
                    1 for item in ai_nodes if str(getattr(item, "trust_status", "") or "").strip().lower() == "trusted"
                )
                ai_state = "connected" if ai_trusted_nodes > 0 else "offline"
            except Exception:
                ai_state = "unknown"

        payload = {
            "subsystems": {
                "core": {"state": core_state},
                "supervisor": {"state": _state_from_bool(supervisor_running, "healthy", "unhealthy")},
                "ai": {
                    "state": ai_state,
                    "trusted_nodes": ai_trusted_nodes,
                    "total_nodes": ai_total_nodes,
                },
                "mqtt": {
                    "state": mqtt_state,
                    "last_message_at": mqtt_last_message_at,
                    "infrastructure": mqtt_infrastructure,
                },
                "scheduler": {
                    "state": scheduler_state,
                    "active_leases": active_leases,
                    "queued_jobs": queued_jobs,
                },
                "workers": {
                    "state": "active" if active_leases > 0 else "idle",
                    "active_count": active_leases,
                },
                "addons": {
                    "state": "degraded" if unhealthy_count > 0 else "healthy",
                    "installed_count": installed_count,
                    "unhealthy_count": unhealthy_count,
                },
            },
            "connectivity": connectivity,
            "samples": {
                "internet_speed": speed,
                "network_throughput": throughput,
                "network_metrics": network_metrics,
            },
        }
        payload["status"] = _derive_overall_status(payload)
        return payload

    return router

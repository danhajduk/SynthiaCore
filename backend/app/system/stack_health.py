from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
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


_sampler = _CachedSampler()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tcp_reachable(host: str, port: int, timeout_s: float = 1.5) -> bool:
    with socket.create_connection((host, port), timeout=timeout_s):
        return True


def _sample_connectivity() -> dict[str, Any]:
    local_host = str(os.getenv("SYNTHIA_LOCAL_NETWORK_CHECK_HOST", "")).strip()
    local_port = int(str(os.getenv("SYNTHIA_LOCAL_NETWORK_CHECK_PORT", "53")).strip() or "53")
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

    try:
        completed = subprocess.run(
            [cli_bin, "--json", "--secure"],
            capture_output=True,
            text=True,
            timeout=max(timeout_s, 1.0),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "speedtest_cli_failed")

        payload = json.loads((completed.stdout or "").strip() or "{}")
        download_bps = float(payload.get("download") or 0.0)
        upload_bps = float(payload.get("upload") or 0.0)
        latency_ms_raw = payload.get("ping")
        latency_ms = round(float(latency_ms_raw), 1) if latency_ms_raw is not None else None

        return {
            "state": "ok",
            "source": "speedtest_cli",
            "download_mbps": round(max(download_bps, 0.0) / 1_000_000.0, 2),
            "upload_mbps": round(max(upload_bps, 0.0) / 1_000_000.0, 2),
            "latency_ms": latency_ms,
            "sampled_at": sampled_at,
            "age_s": 0,
        }
    except Exception:
        return {
            "state": "unavailable",
            "source": "speedtest_cli",
            "download_mbps": None,
            "upload_mbps": None,
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
    subsystems = payload.get("subsystems") or {}
    connectivity = payload.get("connectivity") or {}

    if subsystems.get("supervisor", {}).get("state") != "healthy":
        reasons.append("Supervisor unavailable")

    mqtt_state = subsystems.get("mqtt", {}).get("state")
    if mqtt_state == "disconnected":
        reasons.append("MQTT disconnected")

    scheduler_state = subsystems.get("scheduler", {}).get("state")
    if scheduler_state in {"degraded", "unknown"}:
        reasons.append("Scheduler unavailable")

    worker_state = subsystems.get("workers", {}).get("state")
    if worker_state == "idle":
        reasons.append("No workers active")

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
        if any(reason.startswith("Supervisor") for reason in reasons):
            overall = "attention"
        else:
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
        scheduler_engine = getattr(request.app.state, "scheduler_engine", None)

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
        speed = await _sampler.speed()
        throughput = _throughput_from_stats(stats)
        network_metrics = _network_metrics_from_stats(stats)

        payload = {
            "subsystems": {
                "core": {"state": core_state},
                "supervisor": {"state": _state_from_bool(supervisor_running, "healthy", "unhealthy")},
                "mqtt": {"state": mqtt_state, "last_message_at": mqtt_last_message_at},
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

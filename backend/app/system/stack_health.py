from __future__ import annotations

import asyncio
import os
import socket
import time
import urllib.request
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
        ttl = float(os.getenv("SYNTHIA_SPEEDTEST_SAMPLE_SECONDS", "900") or 900)
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


def _download_speed_mbps(url: str, timeout_s: float, max_bytes: int) -> tuple[float | None, float | None]:
    req = urllib.request.Request(url, method="GET")
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = resp.read(max_bytes)
    elapsed = max(time.perf_counter() - start, 1e-6)
    if not data:
        return None, elapsed * 1000.0
    mbps = (len(data) * 8.0) / elapsed / 1_000_000.0
    return round(mbps, 2), round(elapsed * 1000.0, 1)


def _upload_speed_mbps(url: str, timeout_s: float, upload_bytes: int) -> float | None:
    payload = b"a" * max(upload_bytes, 1)
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/octet-stream")
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        _ = resp.read(16)
    elapsed = max(time.perf_counter() - start, 1e-6)
    mbps = (len(payload) * 8.0) / elapsed / 1_000_000.0
    return round(mbps, 2)


def _sample_speed() -> dict[str, Any]:
    download_url = str(os.getenv("SYNTHIA_SPEEDTEST_DOWNLOAD_URL", "")).strip()
    upload_url = str(os.getenv("SYNTHIA_SPEEDTEST_UPLOAD_URL", "")).strip()
    sampled_at = _now_iso()

    if not download_url or not upload_url:
        return {
            "state": "not_configured",
            "download_mbps": None,
            "upload_mbps": None,
            "latency_ms": None,
            "sampled_at": sampled_at,
            "age_s": 0,
        }

    timeout_s = float(str(os.getenv("SYNTHIA_SPEEDTEST_TIMEOUT_S", "3")).strip() or "3")
    max_download_bytes = int(str(os.getenv("SYNTHIA_SPEEDTEST_DOWNLOAD_BYTES", "250000")).strip() or "250000")
    upload_bytes = int(str(os.getenv("SYNTHIA_SPEEDTEST_UPLOAD_BYTES", "80000")).strip() or "80000")

    try:
        download_mbps, latency_ms = _download_speed_mbps(download_url, timeout_s, max_download_bytes)
        upload_mbps = _upload_speed_mbps(upload_url, timeout_s, upload_bytes)
        return {
            "state": "ok",
            "download_mbps": download_mbps,
            "upload_mbps": upload_mbps,
            "latency_ms": latency_ms,
            "sampled_at": sampled_at,
            "age_s": 0,
        }
    except Exception:
        return {
            "state": "unavailable",
            "download_mbps": None,
            "upload_mbps": None,
            "latency_ms": None,
            "sampled_at": sampled_at,
            "age_s": 0,
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
            },
        }
        payload["status"] = _derive_overall_status(payload)
        return payload

    return router

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import DEFAULT_SUPERVISOR_PORT, DEFAULT_SUPERVISOR_SOCKET
from .models import SupervisorAdmissionContextSummary, SupervisorCoreRuntimeSummary, SupervisorRegisteredRuntimeSummary
from .runtime_store import SupervisorRuntimeNodeRecord, SupervisorRuntimeNodesStore

log = logging.getLogger("synthia.supervisor.client")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_text(name: str, default: str) -> str:
    raw = os.getenv(name)
    return str(raw).strip() if raw is not None else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        return float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _normalize_transport(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if value in {"socket", "http"}:
        return value
    if value in {"disabled", "off", "none"}:
        return "disabled"
    return "socket"


def _normalize_base_url(raw: str) -> str:
    candidate = str(raw or "").strip()
    if not candidate:
        return f"http://127.0.0.1:{DEFAULT_SUPERVISOR_PORT}"
    if "://" not in candidate:
        return f"http://{candidate}"
    return candidate


@dataclass(frozen=True)
class SupervisorClientConfig:
    transport: str
    base_url: str
    unix_socket: str
    timeout_s: float


def supervisor_client_config() -> SupervisorClientConfig:
    transport = _normalize_transport(_env_text("HEXE_SUPERVISOR_API_TRANSPORT", "socket"))
    return SupervisorClientConfig(
        transport=transport,
        base_url=_normalize_base_url(_env_text("HEXE_SUPERVISOR_API_BASE_URL", "")),
        unix_socket=_env_text("HEXE_SUPERVISOR_API_SOCKET", DEFAULT_SUPERVISOR_SOCKET),
        timeout_s=_env_float("HEXE_SUPERVISOR_API_TIMEOUT_S", 2.0),
    )


class SupervisorApiClient:
    def __init__(self, config: SupervisorClientConfig | None = None, client: httpx.Client | None = None) -> None:
        self._config = config or supervisor_client_config()
        self._enabled = self._config.transport != "disabled"
        self._client = client or (self._build_client(self._config) if self._enabled else None)

    def _build_client(self, config: SupervisorClientConfig) -> httpx.Client:
        timeout = httpx.Timeout(config.timeout_s)
        if config.transport == "socket":
            transport = httpx.HTTPTransport(uds=config.unix_socket)
            return httpx.Client(base_url="http://supervisor", transport=transport, timeout=timeout)
        return httpx.Client(base_url=config.base_url.rstrip("/"), timeout=timeout)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self._enabled or self._client is None:
            return None
        try:
            response = self._client.request(method, path, json=payload, params=params)
        except httpx.HTTPError as exc:
            log.debug("Supervisor API request failed: %s %s (%s)", method, path, exc)
            return None
        if response.status_code >= 400:
            log.debug("Supervisor API response error: %s %s -> %s", method, path, response.status_code)
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    def admission_summary(
        self,
        *,
        total_capacity_units: int | None = None,
        reserve_units: int | None = None,
        headroom_pct: float | None = None,
    ) -> SupervisorAdmissionContextSummary | None:
        params: dict[str, Any] = {}
        if total_capacity_units is not None:
            params["total_capacity_units"] = total_capacity_units
        if reserve_units is not None:
            params["reserve_units"] = reserve_units
        if headroom_pct is not None:
            params["headroom_pct"] = headroom_pct
        payload = self._request_json("GET", "/api/supervisor/admission", params=params or None)
        if payload is None:
            return None
        try:
            return SupervisorAdmissionContextSummary.model_validate(payload)
        except Exception:
            log.debug("Supervisor admission payload invalid")
            return None

    def list_registered_runtimes(self) -> list[SupervisorRegisteredRuntimeSummary] | None:
        payload = self._request_json("GET", "/api/supervisor/runtimes")
        if payload is None:
            return None
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            return None
        items: list[SupervisorRegisteredRuntimeSummary] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                items.append(SupervisorRegisteredRuntimeSummary.model_validate(item))
            except Exception:
                continue
        return items

    def get_registered_runtime(self, node_id: str) -> SupervisorRegisteredRuntimeSummary | None:
        payload = self._request_json("GET", f"/api/supervisor/runtimes/{node_id}")
        if payload is None:
            return None
        runtime = payload.get("runtime")
        if not isinstance(runtime, dict):
            return None
        try:
            return SupervisorRegisteredRuntimeSummary.model_validate(runtime)
        except Exception:
            return None

    def refresh_runtime_store(self, store: SupervisorRuntimeNodesStore) -> bool:
        runtimes = self.list_registered_runtimes()
        if runtimes is None:
            return False
        records: list[SupervisorRuntimeNodeRecord] = []
        for runtime in runtimes:
            records.append(
                SupervisorRuntimeNodeRecord(
                    node_id=runtime.node_id,
                    node_name=runtime.node_name,
                    node_type=runtime.node_type,
                    desired_state=runtime.desired_state,
                    runtime_state=runtime.runtime_state,
                    lifecycle_state=runtime.lifecycle_state,
                    health_status=runtime.health_status,
                    registered_at=runtime.registered_at or runtime.updated_at or _utcnow_iso(),
                    updated_at=runtime.updated_at or runtime.registered_at or _utcnow_iso(),
                    host_id=runtime.host_id,
                    hostname=runtime.hostname,
                    api_base_url=runtime.api_base_url,
                    ui_base_url=runtime.ui_base_url,
                    health_detail=runtime.health_detail,
                    freshness_state=runtime.freshness_state or "unknown",
                    last_seen_at=runtime.last_seen_at,
                    last_action=runtime.last_action,
                    last_action_at=runtime.last_action_at,
                    last_error=runtime.last_error,
                    running=runtime.running,
                    runtime_metadata=dict(runtime.runtime_metadata or {}),
                    resource_usage=dict(runtime.resource_usage or {}),
                )
            )
        store.replace_all(records)
        return True

    def list_core_runtimes(self) -> list[SupervisorCoreRuntimeSummary] | None:
        payload = self._request_json("GET", "/api/supervisor/core/runtimes")
        if payload is None:
            return None
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            return None
        items: list[SupervisorCoreRuntimeSummary] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                items.append(SupervisorCoreRuntimeSummary.model_validate(item))
            except Exception:
                continue
        return items

    def get_core_runtime(self, runtime_id: str) -> SupervisorCoreRuntimeSummary | None:
        payload = self._request_json("GET", f"/api/supervisor/core/runtimes/{runtime_id}")
        if payload is None:
            return None
        runtime = payload.get("runtime")
        if not isinstance(runtime, dict):
            return None
        try:
            return SupervisorCoreRuntimeSummary.model_validate(runtime)
        except Exception:
            return None

    def register_core_runtime(self, payload: dict[str, Any]) -> SupervisorCoreRuntimeSummary | None:
        response = self._request_json("POST", "/api/supervisor/core/runtimes/register", payload=payload)
        if response is None:
            return None
        try:
            return SupervisorCoreRuntimeSummary.model_validate(response)
        except Exception:
            return None

    def heartbeat_core_runtime(self, payload: dict[str, Any]) -> SupervisorCoreRuntimeSummary | None:
        response = self._request_json("POST", "/api/supervisor/core/runtimes/heartbeat", payload=payload)
        if response is None:
            return None
        try:
            return SupervisorCoreRuntimeSummary.model_validate(response)
        except Exception:
            return None

    def get_runtime_state(self, runtime_id: str) -> dict[str, Any]:
        payload = self._request_json("GET", f"/api/supervisor/runtime/{runtime_id}")
        if payload is None:
            return {"exists": False}
        return payload

    def apply_cloudflared_config(self, config: dict[str, Any]) -> dict[str, Any]:
        payload = self._request_json("POST", "/api/supervisor/runtime/cloudflared/apply", payload=config)
        if payload is None:
            return {"ok": False, "runtime_state": "unavailable", "error": "supervisor_unavailable"}
        return payload

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Dict
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket
from fastapi.responses import RedirectResponse

from app.api.admin import require_admin_request
from app.reverse_proxy import ReverseProxyService

from .registry import AddonRegistry

log = logging.getLogger("synthia.proxy")

LOCAL_PROXY_RETRIES = 1
LOCAL_PROXY_TIMEOUT_SECONDS = 10.0
LOCAL_PROXY_CIRCUIT_FAIL_THRESHOLD = 3
LOCAL_PROXY_CIRCUIT_OPEN_SECONDS = 30


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.getenv(name, str(default)).strip()))
    except Exception:
        return default


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default)).strip()))
    except Exception:
        return default


@dataclass
class CircuitState:
    failures: int = 0
    open_until_monotonic: float = 0.0

    def is_open(self) -> bool:
        return time.monotonic() < self.open_until_monotonic


class AddonProxy:
    def __init__(self, registry: AddonRegistry) -> None:
        self._registry = registry
        self._proxy = ReverseProxyService()
        self._client = self._proxy._client
        self._circuits: Dict[str, CircuitState] = {}

    async def aclose(self) -> None:
        await self._proxy.aclose()

    def _api_target_base(self, addon_id: str, request: Request) -> str:
        addon = self._registry.registered.get(addon_id)
        if addon is not None:
            return addon.base_url.rstrip("/")
        if addon_id in self._registry.addons:
            return f"{str(request.base_url).rstrip('/')}/api/addons/{quote(addon_id, safe='')}"
        raise HTTPException(status_code=404, detail="registered_addon_not_found")

    def _ui_target_base(self, addon_id: str, request: Request) -> str:
        addon = self._registry.registered.get(addon_id)
        if addon is not None:
            if not bool(getattr(addon, "ui_enabled", False)):
                raise HTTPException(status_code=404, detail="addon_ui_not_enabled")
            raw_ui_base = str(getattr(addon, "ui_base_url", "") or "").strip()
            if not raw_ui_base:
                raise HTTPException(status_code=404, detail="addon_ui_endpoint_not_configured")
            return raw_ui_base.rstrip("/")
        if addon_id in self._registry.addons:
            return f"{str(request.base_url).rstrip('/')}/api/addons/{quote(addon_id, safe='')}"
        raise HTTPException(status_code=404, detail="registered_addon_not_found")

    def _auth_headers(self, addon_id: str) -> dict[str, str]:
        addon = self._registry.registered.get(addon_id)
        if addon is None:
            return {}
        secret_value = ""
        if addon.auth_header_env:
            secret_value = os.getenv(addon.auth_header_env, "")
        if not secret_value:
            return {}
        if addon.auth_mode == "bearer":
            return {"Authorization": f"Bearer {secret_value}"}
        if addon.auth_mode == "header" and addon.auth_header_name:
            return {addon.auth_header_name: secret_value}
        return {}

    def _proxy_tuning(self, addon_id: str) -> tuple[int, httpx.Timeout, int, int]:
        addon = self._registry.registered.get(addon_id)
        if addon is None:
            return (
                _env_int("SYNTHIA_ADDON_PROXY_RETRIES", LOCAL_PROXY_RETRIES, minimum=0),
                httpx.Timeout(_env_float("SYNTHIA_ADDON_PROXY_TIMEOUT_SECONDS", LOCAL_PROXY_TIMEOUT_SECONDS)),
                _env_int(
                    "SYNTHIA_ADDON_PROXY_CIRCUIT_FAIL_THRESHOLD",
                    LOCAL_PROXY_CIRCUIT_FAIL_THRESHOLD,
                    minimum=1,
                ),
                _env_int("SYNTHIA_ADDON_PROXY_CIRCUIT_OPEN_SECONDS", LOCAL_PROXY_CIRCUIT_OPEN_SECONDS, minimum=1),
            )
        return (
            max(0, int(addon.proxy_retries)),
            httpx.Timeout(max(0.1, float(addon.proxy_timeout_s))),
            max(1, int(addon.proxy_circuit_fail_threshold)),
            max(1, int(addon.proxy_circuit_open_seconds)),
        )

    def _open_circuit(self, addon_id: str) -> None:
        addon = self._registry.registered.get(addon_id)
        state = self._circuits.setdefault(addon_id, CircuitState())
        state.failures += 1
        _, _, fail_threshold, open_seconds = self._proxy_tuning(addon_id)
        if state.failures >= fail_threshold:
            state.open_until_monotonic = time.monotonic() + open_seconds
            if addon is not None:
                addon.health_status = "circuit_open"

    def _record_success(self, addon_id: str) -> None:
        addon = self._registry.registered.get(addon_id)
        state = self._circuits.setdefault(addon_id, CircuitState())
        state.failures = 0
        state.open_until_monotonic = 0.0
        if addon is not None:
            addon.health_status = "ok"
            addon.last_seen = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _is_circuit_open(self, addon_id: str) -> bool:
        state = self._circuits.setdefault(addon_id, CircuitState())
        if state.is_open():
            return True
        if state.open_until_monotonic > 0:
            state.open_until_monotonic = 0.0
        return False

    def _ui_health_state(self, addon_id: str) -> tuple[bool, str | None]:
        addon = self._registry.registered.get(addon_id)
        if addon is None:
            return True, None
        status = str(getattr(addon, "health_status", "") or "").strip().lower()
        if status in {"unhealthy", "error", "failed", "failing", "down", "offline", "circuit_open"}:
            return False, f"addon_health_{status}"
        return True, None

    @staticmethod
    def _log_proxy_result(
        *,
        addon_id: str,
        surface: str,
        method: str,
        path: str,
        public_prefix: str,
        status_code: int,
        latency_ms: float,
        outcome: str,
    ) -> None:
        log.info(
            "proxy addon surface=%s addon_id=%s method=%s path=%s prefix=%s status=%s latency_ms=%.1f outcome=%s",
            surface,
            addon_id,
            method,
            path or "/",
            public_prefix,
            status_code,
            latency_ms,
            outcome,
        )

    async def forward_ui(self, request: Request, addon_id: str, path: str = "", *, public_prefix: str = "") -> Response:
        started_at = time.perf_counter()
        effective_public_prefix = public_prefix or f"/addons/{addon_id}"
        if addon_id in self._registry.addons and addon_id not in self._registry.registered:
            local_path = f"/api/addons/{quote(addon_id, safe='')}"
            if path:
                local_path = f"{local_path}/{quote(path.lstrip('/'), safe='/')}"
            if request.url.query:
                local_path = f"{local_path}?{request.url.query}"
            self._log_proxy_result(
                addon_id=addon_id,
                surface="ui",
                method=request.method,
                path=path,
                public_prefix=effective_public_prefix,
                status_code=307,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                outcome="embedded_redirect",
            )
            return RedirectResponse(url=local_path, status_code=307)

        try:
            target_base = self._ui_target_base(addon_id, request)
        except HTTPException as exc:
            self._log_proxy_result(
                addon_id=addon_id,
                surface="ui",
                method=request.method,
                path=path,
                public_prefix=effective_public_prefix,
                status_code=exc.status_code,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                outcome=str(exc.detail),
            )
            return self._proxy.build_ui_error_response(
                status_code=exc.status_code,
                detail=str(exc.detail),
                title="Addon UI Unavailable",
                target_label=addon_id,
                public_prefix=effective_public_prefix,
            )
        healthy, health_detail = self._ui_health_state(addon_id)
        if not healthy:
            self._log_proxy_result(
                addon_id=addon_id,
                surface="ui",
                method=request.method,
                path=path,
                public_prefix=effective_public_prefix,
                status_code=503,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                outcome=str(health_detail or "addon_unhealthy"),
            )
            return self._proxy.build_ui_error_response(
                status_code=503,
                detail=str(health_detail or "addon_unhealthy"),
                title="Addon UI Unavailable",
                target_label=addon_id,
                public_prefix=effective_public_prefix,
            )
        if self._is_circuit_open(addon_id):
            self._log_proxy_result(
                addon_id=addon_id,
                surface="ui",
                method=request.method,
                path=path,
                public_prefix=effective_public_prefix,
                status_code=503,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                outcome="addon_circuit_open",
            )
            return self._proxy.build_ui_error_response(
                status_code=503,
                detail="addon_circuit_open",
                title="Addon UI Unavailable",
                target_label=addon_id,
                public_prefix=effective_public_prefix,
            )

        body = await request.body()
        retries, timeout, _, _ = self._proxy_tuning(addon_id)
        last_exc: Exception | None = None
        headers = self._proxy.build_request_headers(
            request,
            public_prefix=effective_public_prefix,
            extra_headers={
                **self._auth_headers(addon_id),
                "X-Hexe-Addon-Id": addon_id,
            },
        )
        target = self._proxy.build_target_url(target_base, path, request.url.query)

        for attempt in range(retries + 1):
            try:
                upstream = await self._proxy.send(
                    request=request,
                    target_url=target,
                    headers=headers,
                    timeout=timeout,
                    content=body,
                )
                if upstream.status_code >= 500:
                    await upstream.aclose()
                    self._open_circuit(addon_id)
                    if attempt < retries:
                        continue
                else:
                    self._record_success(addon_id)
                content = await upstream.aread()
                response_headers = self._proxy.safe_response_headers(upstream.headers)
                await upstream.aclose()
                content = self._rewrite_root_urls(
                    content,
                    response_headers.get("content-type"),
                    public_prefix=effective_public_prefix,
                )
                self._log_proxy_result(
                    addon_id=addon_id,
                    surface="ui",
                    method=request.method,
                    path=path,
                    public_prefix=effective_public_prefix,
                    status_code=upstream.status_code,
                    latency_ms=(time.perf_counter() - started_at) * 1000.0,
                    outcome="proxied",
                )
                return Response(
                    content=content,
                    status_code=upstream.status_code,
                    headers=response_headers,
                )
            except HTTPException as exc:
                self._log_proxy_result(
                    addon_id=addon_id,
                    surface="ui",
                    method=request.method,
                    path=path,
                    public_prefix=effective_public_prefix,
                    status_code=exc.status_code,
                    latency_ms=(time.perf_counter() - started_at) * 1000.0,
                    outcome=str(exc.detail),
                )
                if exc.status_code != 502:
                    return self._proxy.build_ui_error_response(
                        status_code=exc.status_code,
                        detail=str(exc.detail),
                        title="Addon UI Unavailable",
                        target_label=addon_id,
                        public_prefix=effective_public_prefix,
                    )
                last_exc = RuntimeError(str(exc.detail))
                self._open_circuit(addon_id)
                if attempt < retries:
                    continue
            except httpx.HTTPError as exc:  # pragma: no cover - retained for defensive compatibility
                last_exc = exc
                self._open_circuit(addon_id)
                if attempt < retries:
                    continue

        if last_exc is not None:
            self._log_proxy_result(
                addon_id=addon_id,
                surface="ui",
                method=request.method,
                path=path,
                public_prefix=effective_public_prefix,
                status_code=502,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                outcome=f"addon_proxy_error: {type(last_exc).__name__}",
            )
            return self._proxy.build_ui_error_response(
                status_code=502,
                detail=f"addon_proxy_error: {type(last_exc).__name__}",
                title="Addon UI Unavailable",
                target_label=addon_id,
                public_prefix=effective_public_prefix,
            )
        self._log_proxy_result(
            addon_id=addon_id,
            surface="ui",
            method=request.method,
            path=path,
            public_prefix=effective_public_prefix,
            status_code=502,
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            outcome="addon_proxy_error",
        )
        return self._proxy.build_ui_error_response(
            status_code=502,
            detail="addon_proxy_error",
            title="Addon UI Unavailable",
            target_label=addon_id,
            public_prefix=effective_public_prefix,
        )

    @staticmethod
    def _rewrite_root_urls(content: bytes, content_type: str | None, *, public_prefix: str) -> bytes:
        return ReverseProxyService.rewrite_root_relative_urls(
            content,
            content_type,
            proxy_prefix=public_prefix,
            ignore_prefixes=("/addons/", "/ui/addons/"),
        )

    async def forward_api(self, request: Request, addon_id: str, path: str = "") -> Response:
        started_at = time.perf_counter()
        target_base = self._api_target_base(addon_id, request)
        if self._is_circuit_open(addon_id):
            raise HTTPException(status_code=503, detail="addon_circuit_open")
        body = await request.body()
        retries, timeout, _, _ = self._proxy_tuning(addon_id)
        last_exc: Exception | None = None
        headers = self._proxy.build_request_headers(
            request,
            public_prefix=f"/api/addons/{addon_id}",
            extra_headers={
                **self._auth_headers(addon_id),
                "X-Hexe-Addon-Id": addon_id,
            },
        )
        target = self._proxy.build_target_url(target_base, path, request.url.query)
        for attempt in range(retries + 1):
            try:
                upstream = await self._proxy.send(
                    request=request,
                    target_url=target,
                    headers=headers,
                    timeout=timeout,
                    content=body,
                )
                if upstream.status_code >= 500:
                    await upstream.aclose()
                    self._open_circuit(addon_id)
                    if attempt < retries:
                        continue
                else:
                    self._record_success(addon_id)
                self._log_proxy_result(
                    addon_id=addon_id,
                    surface="api",
                    method=request.method,
                    path=path,
                    public_prefix=f"/api/addons/{addon_id}",
                    status_code=upstream.status_code,
                    latency_ms=(time.perf_counter() - started_at) * 1000.0,
                    outcome="proxied",
                )
                return await self._proxy.stream_response(upstream)
            except HTTPException as exc:
                self._log_proxy_result(
                    addon_id=addon_id,
                    surface="api",
                    method=request.method,
                    path=path,
                    public_prefix=f"/api/addons/{addon_id}",
                    status_code=exc.status_code,
                    latency_ms=(time.perf_counter() - started_at) * 1000.0,
                    outcome=str(exc.detail),
                )
                if exc.status_code != 502:
                    raise
                last_exc = RuntimeError(str(exc.detail))
                self._open_circuit(addon_id)
                if attempt < retries:
                    continue
        if last_exc is not None:
            self._log_proxy_result(
                addon_id=addon_id,
                surface="api",
                method=request.method,
                path=path,
                public_prefix=f"/api/addons/{addon_id}",
                status_code=502,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                outcome=f"addon_api_proxy_error: {type(last_exc).__name__}",
            )
            raise HTTPException(status_code=502, detail=f"addon_api_proxy_error: {type(last_exc).__name__}")
        self._log_proxy_result(
            addon_id=addon_id,
            surface="api",
            method=request.method,
            path=path,
            public_prefix=f"/api/addons/{addon_id}",
            status_code=502,
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            outcome="addon_api_proxy_error",
        )
        raise HTTPException(status_code=502, detail="addon_api_proxy_error")

    async def forward_websocket(self, websocket: WebSocket, addon_id: str, path: str = "", *, public_prefix: str = "") -> None:
        started_at = time.perf_counter()
        if addon_id in self._registry.addons and addon_id not in self._registry.registered:
            self._log_proxy_result(
                addon_id=addon_id,
                surface="ui_ws",
                method="WS",
                path=path,
                public_prefix=public_prefix or f"/addons/{addon_id}",
                status_code=1008,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                outcome="embedded_addon_websocket_proxy_unsupported",
            )
            await websocket.close(code=1008, reason="embedded_addon_websocket_proxy_unsupported")
            return
        healthy, health_detail = self._ui_health_state(addon_id)
        if not healthy:
            self._log_proxy_result(
                addon_id=addon_id,
                surface="ui_ws",
                method="WS",
                path=path,
                public_prefix=public_prefix or f"/addons/{addon_id}",
                status_code=1013,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                outcome=str(health_detail or "addon_unhealthy"),
            )
            await websocket.close(code=1013, reason=str(health_detail or "addon_unhealthy"))
            return
        target_base = self._ui_target_base(addon_id, websocket)
        target = self._proxy.build_websocket_target_url(target_base, path, websocket.url.query)
        await self._proxy.proxy_websocket(
            websocket,
            target_url=target,
            public_prefix=public_prefix or f"/addons/{addon_id}",
            extra_headers={
                **self._auth_headers(addon_id),
                "X-Hexe-Addon-Id": addon_id,
            },
        )
        self._log_proxy_result(
            addon_id=addon_id,
            surface="ui_ws",
            method="WS",
            path=path,
            public_prefix=public_prefix or f"/addons/{addon_id}",
            status_code=101,
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            outcome="proxied",
        )


def build_proxy_router(proxy: AddonProxy) -> APIRouter:
    router = APIRouter()

    @router.api_route("/api/addons/{addon_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def proxy_api(addon_id: str, path: str, request: Request):
        require_admin_request(request)
        return await proxy.forward_api(request, addon_id, path)

    @router.api_route("/api/addons/{addon_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def proxy_api_root(addon_id: str, request: Request):
        require_admin_request(request)
        return await proxy.forward_api(request, addon_id, "")

    @router.api_route("/addons/{addon_id}/{path:path}", methods=["GET", "HEAD"])
    async def proxy_ui_canonical(addon_id: str, path: str, request: Request):
        require_admin_request(request)
        return await proxy.forward_ui(request, addon_id, path, public_prefix=f"/addons/{addon_id}")

    @router.api_route("/addons/{addon_id}/", methods=["GET", "HEAD"])
    async def proxy_ui_canonical_root(addon_id: str, request: Request):
        require_admin_request(request)
        return await proxy.forward_ui(request, addon_id, "", public_prefix=f"/addons/{addon_id}")

    @router.api_route("/addons/{addon_id}", methods=["GET", "HEAD"])
    async def proxy_ui_canonical_root_no_slash(addon_id: str, request: Request):
        require_admin_request(request)
        return await proxy.forward_ui(request, addon_id, "", public_prefix=f"/addons/{addon_id}")

    @router.api_route("/ui/addons/{addon_id}/{path:path}", methods=["GET", "HEAD"])
    async def proxy_ui(addon_id: str, path: str, request: Request):
        require_admin_request(request)
        return await proxy.forward_ui(request, addon_id, path, public_prefix=f"/ui/addons/{addon_id}")

    @router.api_route("/ui/addons/{addon_id}", methods=["GET", "HEAD"])
    async def proxy_ui_root(addon_id: str, request: Request):
        require_admin_request(request)
        return await proxy.forward_ui(request, addon_id, "", public_prefix=f"/ui/addons/{addon_id}")

    @router.websocket("/addons/{addon_id}/{path:path}")
    async def proxy_ui_canonical_websocket(addon_id: str, path: str, websocket: WebSocket):
        try:
            require_admin_request(websocket)
        except HTTPException:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        await proxy.forward_websocket(websocket, addon_id, path, public_prefix=f"/addons/{addon_id}")

    @router.websocket("/addons/{addon_id}/")
    async def proxy_ui_canonical_root_websocket(addon_id: str, websocket: WebSocket):
        try:
            require_admin_request(websocket)
        except HTTPException:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        await proxy.forward_websocket(websocket, addon_id, "", public_prefix=f"/addons/{addon_id}")

    @router.websocket("/ui/addons/{addon_id}/{path:path}")
    async def proxy_ui_websocket(addon_id: str, path: str, websocket: WebSocket):
        try:
            require_admin_request(websocket)
        except HTTPException:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        await proxy.forward_websocket(websocket, addon_id, path, public_prefix=f"/ui/addons/{addon_id}")

    @router.websocket("/ui/addons/{addon_id}")
    async def proxy_ui_root_websocket(addon_id: str, websocket: WebSocket):
        try:
            require_admin_request(websocket)
        except HTTPException:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        await proxy.forward_websocket(websocket, addon_id, "", public_prefix=f"/ui/addons/{addon_id}")

    return router

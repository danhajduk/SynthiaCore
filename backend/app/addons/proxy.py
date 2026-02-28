from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Dict
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from .registry import AddonRegistry

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

REQUEST_HEADER_ALLOWLIST = {
    "accept",
    "accept-encoding",
    "accept-language",
    "cache-control",
    "content-type",
    "if-match",
    "if-none-match",
    "if-modified-since",
    "if-unmodified-since",
    "range",
    "user-agent",
}


@dataclass
class CircuitState:
    failures: int = 0
    open_until_monotonic: float = 0.0

    def is_open(self) -> bool:
        return time.monotonic() < self.open_until_monotonic


class AddonProxy:
    def __init__(self, registry: AddonRegistry) -> None:
        self._registry = registry
        self._client = httpx.AsyncClient(follow_redirects=False)
        self._circuits: Dict[str, CircuitState] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    def _target_base(self, addon_id: str) -> str:
        addon = self._registry.registered.get(addon_id)
        if addon is None:
            raise HTTPException(status_code=404, detail="registered_addon_not_found")
        return addon.base_url.rstrip("/")

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

    def _open_circuit(self, addon_id: str) -> None:
        addon = self._registry.registered[addon_id]
        state = self._circuits.setdefault(addon_id, CircuitState())
        state.failures += 1
        if state.failures >= max(1, int(addon.proxy_circuit_fail_threshold)):
            state.open_until_monotonic = time.monotonic() + max(1, int(addon.proxy_circuit_open_seconds))
            addon.health_status = "circuit_open"

    def _record_success(self, addon_id: str) -> None:
        addon = self._registry.registered[addon_id]
        state = self._circuits.setdefault(addon_id, CircuitState())
        state.failures = 0
        state.open_until_monotonic = 0.0
        addon.health_status = "ok"
        addon.last_seen = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _is_circuit_open(self, addon_id: str) -> bool:
        state = self._circuits.setdefault(addon_id, CircuitState())
        if state.is_open():
            return True
        if state.open_until_monotonic > 0:
            state.open_until_monotonic = 0.0
        return False

    def _safe_request_headers(self, request: Request, addon_id: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key, value in request.headers.items():
            lk = key.lower()
            if lk in HOP_BY_HOP_HEADERS:
                continue
            if lk not in REQUEST_HEADER_ALLOWLIST:
                continue
            headers[key] = value
        headers.update(self._auth_headers(addon_id))
        return headers

    @staticmethod
    def _safe_response_headers(source: httpx.Headers) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key, value in source.items():
            if key.lower() in HOP_BY_HOP_HEADERS:
                continue
            headers[key] = value
        return headers

    async def forward(self, request: Request, addon_id: str, path: str = "") -> Response:
        if addon_id not in self._registry.registered:
            raise HTTPException(status_code=404, detail="registered_addon_not_found")
        if self._is_circuit_open(addon_id):
            raise HTTPException(status_code=503, detail="addon_circuit_open")

        addon = self._registry.registered[addon_id]
        target = (
            f"{self._target_base(addon_id)}/{quote(path.lstrip('/'), safe='/')}"
            if path
            else self._target_base(addon_id)
        )
        if request.url.query:
            target = f"{target}?{request.url.query}"
        body = await request.body()
        retries = max(0, int(addon.proxy_retries))
        timeout = httpx.Timeout(max(0.1, float(addon.proxy_timeout_s)))
        last_exc: Exception | None = None

        for attempt in range(retries + 1):
            try:
                upstream = await self._client.request(
                    method=request.method,
                    url=target,
                    content=body,
                    headers=self._safe_request_headers(request, addon_id),
                    timeout=timeout,
                )
                if upstream.status_code >= 500:
                    self._open_circuit(addon_id)
                    if attempt < retries:
                        continue
                else:
                    self._record_success(addon_id)
                return Response(
                    content=upstream.content,
                    status_code=upstream.status_code,
                    headers=self._safe_response_headers(upstream.headers),
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                self._open_circuit(addon_id)
                if attempt < retries:
                    continue

        if last_exc is not None:
            raise HTTPException(status_code=502, detail=f"addon_proxy_error: {type(last_exc).__name__}")
        raise HTTPException(status_code=502, detail="addon_proxy_error")


def build_proxy_router(proxy: AddonProxy) -> APIRouter:
    router = APIRouter()

    @router.api_route("/api/addons/{addon_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def proxy_api(addon_id: str, path: str, request: Request):
        return await proxy.forward(request, addon_id, path)

    @router.api_route("/api/addons/{addon_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def proxy_api_root(addon_id: str, request: Request):
        return await proxy.forward(request, addon_id, "")

    @router.api_route("/ui/addons/{addon_id}/{path:path}", methods=["GET", "HEAD"])
    async def proxy_ui(addon_id: str, path: str, request: Request):
        return await proxy.forward(request, addon_id, path)

    @router.api_route("/ui/addons/{addon_id}", methods=["GET", "HEAD"])
    async def proxy_ui_root(addon_id: str, request: Request):
        return await proxy.forward(request, addon_id, "")

    return router

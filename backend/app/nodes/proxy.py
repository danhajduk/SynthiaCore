from __future__ import annotations

import logging
import os
import re
import time
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket

from app.api.admin import require_admin_request
from app.reverse_proxy import ReverseProxyService
from app.ui_target_resolver import UiTargetResolver
from .service import NodesDomainService

log = logging.getLogger("synthia.proxy")
HTML_ROOT_URL_ATTR_RE = re.compile(r'(?P<prefix>\b(?:src|href|action)=["\'])(?P<path>/[^"\']*)')
ROOT_URL_STRING_RE = re.compile(r'(?P<quote>["\'])(?P<path>/[^"\']*)(?P=quote)')


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.getenv(name, str(default)).strip()))
    except Exception:
        return default


NODE_PROXY_TIMEOUT_SECONDS = 10.0
NODE_UI_HEALTH_TIMEOUT_SECONDS = 2.0


class NodeUiProxy:
    def __init__(self, service: NodesDomainService) -> None:
        self._service = service
        self._targets = UiTargetResolver(nodes_service=service)
        self._proxy = ReverseProxyService(
            client=httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(_env_float("SYNTHIA_NODE_PROXY_TIMEOUT_SECONDS", NODE_PROXY_TIMEOUT_SECONDS)),
            )
        )

    async def aclose(self) -> None:
        await self._proxy.aclose()

    def _target_base(self, node_id: str, request: Request) -> str:
        return self._targets.resolve_node_ui(node_id).target_base

    def _api_target_base(self, node_id: str, request: Request) -> str:
        return self._targets.resolve_node_api(node_id).target_base

    @staticmethod
    def _log_proxy_result(
        *,
        node_id: str,
        surface: str,
        method: str,
        path: str,
        public_prefix: str,
        status_code: int,
        latency_ms: float,
        outcome: str,
    ) -> None:
        log.info(
            "proxy node surface=%s node_id=%s method=%s path=%s prefix=%s status=%s latency_ms=%.1f outcome=%s",
            surface,
            node_id,
            method,
            path or "/",
            public_prefix,
            status_code,
            latency_ms,
            outcome,
        )

    async def _ui_health_state(self, node_id: str) -> tuple[bool, str | None]:
        raw_endpoint = self._targets.resolve_node_ui(node_id).health_endpoint
        if not raw_endpoint:
            return True, None
        return await self._proxy.probe_health(
            raw_endpoint,
            timeout=httpx.Timeout(_env_float("SYNTHIA_NODE_UI_HEALTH_TIMEOUT_SECONDS", NODE_UI_HEALTH_TIMEOUT_SECONDS)),
        )

    async def forward(self, request: Request, node_id: str, path: str = "", *, public_prefix: str = "") -> Response:
        started_at = time.perf_counter()
        effective_public_prefix = public_prefix or f"/nodes/{node_id}/ui"
        try:
            resolved_target = self._targets.resolve_node_ui(node_id)
            target_base = resolved_target.target_base
        except HTTPException as exc:
            self._log_proxy_result(
                node_id=node_id,
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
                title="Node UI Unavailable",
                target_label=node_id,
                public_prefix=effective_public_prefix,
            )
        healthy, health_detail = await self._ui_health_state(node_id)
        if not healthy:
            self._log_proxy_result(
                node_id=node_id,
                surface="ui",
                method=request.method,
                path=path,
                public_prefix=effective_public_prefix,
                status_code=503,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                outcome=str(health_detail or "node_unhealthy"),
            )
            return self._proxy.build_ui_error_response(
                status_code=503,
                detail=str(health_detail or "node_unhealthy"),
                title="Node UI Unavailable",
                target_label=node_id,
                public_prefix=effective_public_prefix,
            )
        target = self._proxy.build_target_url(target_base, path, request.url.query)
        headers = self._proxy.build_request_headers(
            request,
            public_prefix=effective_public_prefix,
            extra_headers={"X-Hexe-Node-Id": node_id},
        )
        try:
            upstream = await self._proxy.send(
                request=request,
                target_url=target,
                headers=headers,
            )
        except HTTPException as exc:
            if exc.status_code == 502:
                self._log_proxy_result(
                    node_id=node_id,
                    surface="ui",
                    method=request.method,
                    path=path,
                    public_prefix=effective_public_prefix,
                    status_code=502,
                    latency_ms=(time.perf_counter() - started_at) * 1000.0,
                    outcome=f"node_ui_proxy_error: {str(exc.detail).removeprefix('proxy_error: ')}",
                )
                return self._proxy.build_ui_error_response(
                    status_code=502,
                    detail=f"node_ui_proxy_error: {str(exc.detail).removeprefix('proxy_error: ')}",
                    title="Node UI Unavailable",
                    target_label=node_id,
                    public_prefix=effective_public_prefix,
                )
            self._log_proxy_result(
                node_id=node_id,
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
                title="Node UI Unavailable",
                target_label=node_id,
                public_prefix=effective_public_prefix,
            )
        content = await upstream.aread()
        response_headers = self._proxy.safe_response_headers(upstream.headers)
        await upstream.aclose()
        content = self._rewrite_root_urls(
            content,
            response_headers.get("content-type"),
            public_prefix=effective_public_prefix,
            api_public_prefix=f"/api/nodes/{node_id}",
        )
        self._log_proxy_result(
            node_id=node_id,
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

    @staticmethod
    def _rewrite_root_urls(
        content: bytes,
        content_type: str | None,
        *,
        public_prefix: str,
        api_public_prefix: str,
    ) -> bytes:
        normalized_type = str(content_type or "").lower()
        is_html = "text/html" in normalized_type
        is_js = "javascript" in normalized_type
        is_css = "text/css" in normalized_type
        if not (is_html or is_js or is_css):
            return content
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return content

        normalized_ui_prefix = public_prefix.rstrip("/")
        normalized_api_prefix = api_public_prefix.rstrip("/")
        ignore_prefixes = ("/nodes/", "/ui/nodes/", "/api/nodes/")

        def should_rewrite(path: str) -> bool:
            if not path.startswith("/") or path == "/":
                return False
            for prefix in ignore_prefixes:
                normalized = str(prefix or "").rstrip("/")
                if normalized and (path == normalized or path.startswith(f"{normalized}/")):
                    return False
            return True

        def rewrite_path(path: str) -> str:
            if not should_rewrite(path):
                return path
            if path == "/api":
                return normalized_api_prefix
            if path.startswith("/api/"):
                return f"{normalized_api_prefix}{path.removeprefix('/api')}"
            return f"{normalized_ui_prefix}{path}"

        rewritten = text
        if is_html:
            rewritten = HTML_ROOT_URL_ATTR_RE.sub(
                lambda match: f"{match.group('prefix')}{rewrite_path(match.group('path'))}",
                rewritten,
            )
        rewritten = ROOT_URL_STRING_RE.sub(
            lambda match: f"{match.group('quote')}{rewrite_path(match.group('path'))}{match.group('quote')}",
            rewritten,
        )
        return rewritten.encode("utf-8")

    async def forward_websocket(self, websocket: WebSocket, node_id: str, path: str = "", *, public_prefix: str = "") -> None:
        started_at = time.perf_counter()
        healthy, health_detail = await self._ui_health_state(node_id)
        if not healthy:
            self._log_proxy_result(
                node_id=node_id,
                surface="ui_ws",
                method="WS",
                path=path,
                public_prefix=public_prefix or f"/nodes/{node_id}/ui",
                status_code=1013,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                outcome=str(health_detail or "node_unhealthy"),
            )
            await websocket.close(code=1013, reason=str(health_detail or "node_unhealthy"))
            return
        target_base = self._target_base(node_id, websocket)
        target = self._proxy.build_websocket_target_url(target_base, path, websocket.url.query)
        await self._proxy.proxy_websocket(
            websocket,
            target_url=target,
            public_prefix=public_prefix or f"/nodes/{node_id}/ui",
            extra_headers={"X-Hexe-Node-Id": node_id},
        )
        self._log_proxy_result(
            node_id=node_id,
            surface="ui_ws",
            method="WS",
            path=path,
            public_prefix=public_prefix or f"/nodes/{node_id}/ui",
            status_code=101,
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            outcome="proxied",
        )

    async def forward_api(self, request: Request, node_id: str, path: str = "") -> Response:
        started_at = time.perf_counter()
        target_base = self._api_target_base(node_id, request)
        target = self._proxy.build_target_url(target_base, path, request.url.query)
        headers = self._proxy.build_request_headers(
            request,
            public_prefix=f"/api/nodes/{node_id}",
            extra_headers={"X-Hexe-Node-Id": node_id},
        )
        try:
            upstream = await self._proxy.send(
                request=request,
                target_url=target,
                headers=headers,
            )
        except HTTPException as exc:
            if exc.status_code == 502:
                self._log_proxy_result(
                    node_id=node_id,
                    surface="api",
                    method=request.method,
                    path=path,
                    public_prefix=f"/api/nodes/{node_id}",
                    status_code=502,
                    latency_ms=(time.perf_counter() - started_at) * 1000.0,
                    outcome=f"node_api_proxy_error: {str(exc.detail).removeprefix('proxy_error: ')}",
                )
                raise HTTPException(status_code=502, detail=f"node_api_proxy_error: {str(exc.detail).removeprefix('proxy_error: ')}")
            raise
        self._log_proxy_result(
            node_id=node_id,
            surface="api",
            method=request.method,
            path=path,
            public_prefix=f"/api/nodes/{node_id}",
            status_code=upstream.status_code,
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            outcome="proxied",
        )
        return await self._proxy.stream_response(upstream)


def build_node_ui_proxy_router(proxy: NodeUiProxy) -> APIRouter:
    router = APIRouter()

    @router.api_route("/nodes/{node_id}/ui/{path:path}", methods=["GET", "HEAD"])
    async def proxy_node_ui_canonical(node_id: str, path: str, request: Request):
        require_admin_request(request)
        return await proxy.forward(request, node_id, path, public_prefix=f"/nodes/{node_id}/ui")

    @router.api_route("/nodes/{node_id}/ui/", methods=["GET", "HEAD"])
    async def proxy_node_ui_canonical_root(node_id: str, request: Request):
        require_admin_request(request)
        return await proxy.forward(request, node_id, "", public_prefix=f"/nodes/{node_id}/ui")

    @router.api_route("/nodes/{node_id}/ui", methods=["GET", "HEAD"])
    async def proxy_node_ui_canonical_root_no_slash(node_id: str, request: Request):
        require_admin_request(request)
        return await proxy.forward(request, node_id, "", public_prefix=f"/nodes/{node_id}/ui")

    @router.api_route("/ui/nodes/{node_id}/{path:path}", methods=["GET", "HEAD"])
    async def proxy_node_ui(node_id: str, path: str, request: Request):
        require_admin_request(request)
        return await proxy.forward(request, node_id, path, public_prefix=f"/ui/nodes/{node_id}")

    @router.api_route("/ui/nodes/{node_id}", methods=["GET", "HEAD"])
    async def proxy_node_ui_root(node_id: str, request: Request):
        require_admin_request(request)
        return await proxy.forward(request, node_id, "", public_prefix=f"/ui/nodes/{node_id}")

    @router.api_route(
        "/api/nodes/{node_id}/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    async def proxy_node_api(node_id: str, path: str, request: Request):
        require_admin_request(request)
        return await proxy.forward_api(request, node_id, path)

    @router.api_route(
        "/api/nodes/{node_id}/",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    async def proxy_node_api_root(node_id: str, request: Request):
        require_admin_request(request)
        return await proxy.forward_api(request, node_id, "")

    @router.websocket("/nodes/{node_id}/ui/{path:path}")
    async def proxy_node_ui_canonical_websocket(node_id: str, path: str, websocket: WebSocket):
        try:
            require_admin_request(websocket)
        except HTTPException:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        await proxy.forward_websocket(websocket, node_id, path, public_prefix=f"/nodes/{node_id}/ui")

    @router.websocket("/nodes/{node_id}/ui/")
    async def proxy_node_ui_canonical_root_websocket(node_id: str, websocket: WebSocket):
        try:
            require_admin_request(websocket)
        except HTTPException:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        await proxy.forward_websocket(websocket, node_id, "", public_prefix=f"/nodes/{node_id}/ui")

    @router.websocket("/ui/nodes/{node_id}/{path:path}")
    async def proxy_node_ui_websocket(node_id: str, path: str, websocket: WebSocket):
        try:
            require_admin_request(websocket)
        except HTTPException:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        await proxy.forward_websocket(websocket, node_id, path, public_prefix=f"/ui/nodes/{node_id}")

    @router.websocket("/ui/nodes/{node_id}")
    async def proxy_node_ui_root_websocket(node_id: str, websocket: WebSocket):
        try:
            require_admin_request(websocket)
        except HTTPException:
            await websocket.close(code=4401, reason="Unauthorized")
            return
        await proxy.forward_websocket(websocket, node_id, "", public_prefix=f"/ui/nodes/{node_id}")

    return router

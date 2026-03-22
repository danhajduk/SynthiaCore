from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket

from app.proxy_routes import node_ui_proxy_base
from app.reverse_proxy import ReverseProxyService
from .service import NodesDomainService

HTML_ROOT_URL_ATTR_RE = re.compile(r'(?P<prefix>\b(?:src|href|action)=["\'])(?P<path>/[^"\']*)')
ROOT_URL_STRING_RE = re.compile(r'(?P<quote>["\'])(?P<path>/(?!(?:nodes/[^/]+/ui(?:/|$)|ui/nodes/|/))[^"\']*)(?P=quote)')


class NodeUiProxy:
    def __init__(self, service: NodesDomainService) -> None:
        self._service = service
        self._proxy = ReverseProxyService(client=httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(10.0)))

    async def aclose(self) -> None:
        await self._proxy.aclose()

    def _target_base(self, node_id: str, request: Request) -> str:
        node = self._service.get_node(node_id)
        if not bool(getattr(node, "ui_enabled", False)):
            raise HTTPException(status_code=404, detail="node_ui_not_enabled")
        raw_endpoint = str(getattr(node, "ui_base_url", "") or "").strip()
        if raw_endpoint:
            parsed = urlsplit(raw_endpoint)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return raw_endpoint.rstrip("/")
            raise HTTPException(status_code=502, detail="node_ui_endpoint_invalid")
        raise HTTPException(status_code=404, detail="node_ui_endpoint_not_configured")

    def _api_target_base(self, node_id: str, request: Request) -> str:
        ui_base = self._target_base(node_id, request)
        parsed = urlsplit(ui_base)
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))

    @staticmethod
    def _rewrite_root_urls(content: bytes, content_type: str | None, node_id: str) -> bytes:
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
        proxy_prefix = node_ui_proxy_base(node_id).rstrip("/")
        rewritten = text
        if is_html:
            rewritten = HTML_ROOT_URL_ATTR_RE.sub(
                lambda match: f"{match.group('prefix')}{proxy_prefix}{match.group('path')}",
                rewritten,
            )
        rewritten = ROOT_URL_STRING_RE.sub(
            lambda match: f"{match.group('quote')}{proxy_prefix}{match.group('path')}{match.group('quote')}",
            rewritten,
        )
        return rewritten.encode("utf-8")

    async def forward(self, request: Request, node_id: str, path: str = "", *, public_prefix: str = "") -> Response:
        target_base = self._target_base(node_id, request)
        target = self._proxy.build_target_url(target_base, path, request.url.query)
        headers = self._proxy.build_request_headers(
            request,
            public_prefix=public_prefix or node_ui_proxy_base(node_id),
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
                raise HTTPException(status_code=502, detail=f"node_ui_proxy_error: {str(exc.detail).removeprefix('proxy_error: ')}")
            raise
        content = await upstream.aread()
        response_headers = self._proxy.safe_response_headers(upstream.headers)
        await upstream.aclose()
        content = self._rewrite_root_urls(
            content,
            response_headers.get("content-type"),
            node_id,
        )
        return Response(
            content=content,
            status_code=upstream.status_code,
            headers=response_headers,
        )

    async def forward_websocket(self, websocket: WebSocket, node_id: str, path: str = "", *, public_prefix: str = "") -> None:
        target_base = self._target_base(node_id, websocket)
        target = self._proxy.build_websocket_target_url(target_base, path, websocket.url.query)
        await self._proxy.proxy_websocket(
            websocket,
            target_url=target,
            public_prefix=public_prefix or node_ui_proxy_base(node_id),
            extra_headers={"X-Hexe-Node-Id": node_id},
        )

    async def forward_api(self, request: Request, node_id: str, path: str = "") -> Response:
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
                raise HTTPException(status_code=502, detail=f"node_api_proxy_error: {str(exc.detail).removeprefix('proxy_error: ')}")
            raise
        return await self._proxy.stream_response(upstream)


def build_node_ui_proxy_router(proxy: NodeUiProxy) -> APIRouter:
    router = APIRouter()

    @router.api_route("/nodes/{node_id}/ui/{path:path}", methods=["GET", "HEAD"])
    async def proxy_node_ui_canonical(node_id: str, path: str, request: Request):
        return await proxy.forward(request, node_id, path, public_prefix=f"/nodes/{node_id}/ui")

    @router.api_route("/nodes/{node_id}/ui/", methods=["GET", "HEAD"])
    async def proxy_node_ui_canonical_root(node_id: str, request: Request):
        return await proxy.forward(request, node_id, "", public_prefix=f"/nodes/{node_id}/ui")

    @router.api_route("/nodes/{node_id}/ui", methods=["GET", "HEAD"])
    async def proxy_node_ui_canonical_root_no_slash(node_id: str, request: Request):
        return await proxy.forward(request, node_id, "", public_prefix=f"/nodes/{node_id}/ui")

    @router.api_route("/ui/nodes/{node_id}/{path:path}", methods=["GET", "HEAD"])
    async def proxy_node_ui(node_id: str, path: str, request: Request):
        return await proxy.forward(request, node_id, path, public_prefix=f"/ui/nodes/{node_id}")

    @router.api_route("/ui/nodes/{node_id}", methods=["GET", "HEAD"])
    async def proxy_node_ui_root(node_id: str, request: Request):
        return await proxy.forward(request, node_id, "", public_prefix=f"/ui/nodes/{node_id}")

    @router.api_route(
        "/api/nodes/{node_id}/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    async def proxy_node_api(node_id: str, path: str, request: Request):
        return await proxy.forward_api(request, node_id, path)

    @router.api_route(
        "/api/nodes/{node_id}/",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    async def proxy_node_api_root(node_id: str, request: Request):
        return await proxy.forward_api(request, node_id, "")

    @router.websocket("/nodes/{node_id}/ui/{path:path}")
    async def proxy_node_ui_canonical_websocket(node_id: str, path: str, websocket: WebSocket):
        await proxy.forward_websocket(websocket, node_id, path, public_prefix=f"/nodes/{node_id}/ui")

    @router.websocket("/nodes/{node_id}/ui/")
    async def proxy_node_ui_canonical_root_websocket(node_id: str, websocket: WebSocket):
        await proxy.forward_websocket(websocket, node_id, "", public_prefix=f"/nodes/{node_id}/ui")

    @router.websocket("/ui/nodes/{node_id}/{path:path}")
    async def proxy_node_ui_websocket(node_id: str, path: str, websocket: WebSocket):
        await proxy.forward_websocket(websocket, node_id, path, public_prefix=f"/ui/nodes/{node_id}")

    @router.websocket("/ui/nodes/{node_id}")
    async def proxy_node_ui_root_websocket(node_id: str, websocket: WebSocket):
        await proxy.forward_websocket(websocket, node_id, "", public_prefix=f"/ui/nodes/{node_id}")

    return router

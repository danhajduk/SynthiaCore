from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from .service import NodesDomainService

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

HTML_ROOT_URL_ATTR_RE = re.compile(r'(?P<prefix>\b(?:src|href|action)=["\'])(?P<path>/[^"\']*)')
ROOT_URL_STRING_RE = re.compile(r'(?P<quote>["\'])(?P<path>/(?!ui/nodes/|/)[^"\']*)(?P=quote)')


class NodeUiProxy:
    def __init__(self, service: NodesDomainService) -> None:
        self._service = service
        self._client = httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(10.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _build_target_url(target_base: str, path: str, query: str = "") -> str:
        target = f"{target_base}/{quote(path.lstrip('/'), safe='/@:')}" if path else target_base
        if query:
            target = f"{target}?{query}"
        return target

    def _target_base(self, node_id: str, request: Request) -> str:
        node = self._service.get_node(node_id)
        raw_endpoint = str(getattr(node, "requested_ui_endpoint", "") or "").strip()
        if raw_endpoint:
            parsed = urlsplit(raw_endpoint)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return raw_endpoint.rstrip("/")
            raise HTTPException(status_code=502, detail="node_ui_endpoint_invalid")
        raw_host = str(getattr(node, "requested_hostname", "") or "").strip()
        if not raw_host:
            raise HTTPException(status_code=404, detail="node_ui_endpoint_not_configured")
        if raw_host.startswith("http://") or raw_host.startswith("https://"):
            return raw_host.rstrip("/")
        scheme = "https" if request.url.scheme == "https" else "http"
        return f"{scheme}://{raw_host.rstrip('/')}"

    def _safe_request_headers(self, request: Request) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key, value in request.headers.items():
            lk = key.lower()
            if lk in HOP_BY_HOP_HEADERS or lk not in REQUEST_HEADER_ALLOWLIST:
                continue
            headers[key] = value
        return headers

    @staticmethod
    def _safe_response_headers(source: httpx.Headers) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key, value in source.items():
            if key.lower() in HOP_BY_HOP_HEADERS:
                continue
            headers[key] = value
        return headers

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
        proxy_prefix = f"/ui/nodes/{quote(node_id, safe='')}"
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

    async def forward(self, request: Request, node_id: str, path: str = "") -> Response:
        target_base = self._target_base(node_id, request)
        target = self._build_target_url(target_base, path, request.url.query)
        body = await request.body()
        try:
            upstream = await self._client.request(
                method=request.method,
                url=target,
                content=body,
                headers=self._safe_request_headers(request),
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"node_ui_proxy_error: {type(exc).__name__}")
        content = self._rewrite_root_urls(
            upstream.content,
            upstream.headers.get("content-type"),
            node_id,
        )
        return Response(
            content=content,
            status_code=upstream.status_code,
            headers=self._safe_response_headers(upstream.headers),
        )


def build_node_ui_proxy_router(proxy: NodeUiProxy) -> APIRouter:
    router = APIRouter()

    @router.api_route("/ui/nodes/{node_id}/{path:path}", methods=["GET", "HEAD"])
    async def proxy_node_ui(node_id: str, path: str, request: Request):
        return await proxy.forward(request, node_id, path)

    @router.api_route("/ui/nodes/{node_id}", methods=["GET", "HEAD"])
    async def proxy_node_ui_root(node_id: str, request: Request):
        return await proxy.forward(request, node_id, "")

    return router

from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

PROXY_REDIRECT_STATUS = 307

_NODE_UI_BASE_RE = re.compile(r"^/nodes/proxy/(?P<node_id>[^/]+)$")
_NODE_UI_NAVIGATION_RE = re.compile(r"^/nodes/proxy/ui/(?P<node_id>[^/]+)(?:/(?P<path>.*))?$")
_ADDON_UI_BASE_RE = re.compile(r"^/addons/proxy/(?P<addon_id>[^/]+)$")
_LEGACY_CANONICAL_NODE_UI_RE = re.compile(r"^/nodes/(?P<node_id>[^/]+)/ui(?:/(?P<path>.*))?$")
_LEGACY_NODE_UI_RE = re.compile(r"^/ui/nodes/(?P<node_id>[^/]+)(?:/(?P<path>.*))?$")
_LEGACY_ADDON_UI_RE = re.compile(r"^/ui/addons/(?P<addon_id>[^/]+)(?:/(?P<path>.*))?$")


def _encode_id(raw: str) -> str:
    return quote(str(raw or "").strip(), safe="")


def _encode_tail(path: str = "") -> str:
    return quote(str(path or "").lstrip("/"), safe="/@:")


def node_api_proxy_base(node_id: str) -> str:
    return f"/nodes/proxy/{_encode_id(node_id)}/"


def node_ui_proxy_base(node_id: str) -> str:
    return f"/nodes/proxy/ui/{_encode_id(node_id)}/"


def node_ui_proxy_path(node_id: str, path: str = "") -> str:
    base = node_ui_proxy_base(node_id)
    tail = _encode_tail(path)
    return f"{base}{tail}" if tail else base


def addon_ui_proxy_base(addon_id: str) -> str:
    return f"/addons/proxy/{_encode_id(addon_id)}/"


def addon_ui_proxy_path(addon_id: str, path: str = "") -> str:
    base = addon_ui_proxy_base(addon_id)
    tail = _encode_tail(path)
    return f"{base}{tail}" if tail else base


def _with_query(path: str, request: Request) -> str:
    query = str(request.url.query or "")
    return f"{path}?{query}" if query else path


def resolve_proxy_redirect_path(path: str) -> str | None:
    if _NODE_UI_NAVIGATION_RE.match(path):
        return None

    match = _NODE_UI_BASE_RE.match(path)
    if match:
        return node_api_proxy_base(match.group("node_id"))

    match = _LEGACY_CANONICAL_NODE_UI_RE.match(path)
    if match:
        return node_ui_proxy_path(match.group("node_id"), match.group("path") or "")

    match = _ADDON_UI_BASE_RE.match(path)
    if match:
        return addon_ui_proxy_base(match.group("addon_id"))

    match = _LEGACY_NODE_UI_RE.match(path)
    if match:
        return node_ui_proxy_path(match.group("node_id"), match.group("path") or "")

    match = _LEGACY_ADDON_UI_RE.match(path)
    if match:
        return addon_ui_proxy_path(match.group("addon_id"), match.group("path") or "")

    return None


class ProxyRouteRedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        target = resolve_proxy_redirect_path(request.url.path)
        if target and target != request.url.path:
            return RedirectResponse(url=_with_query(target, request), status_code=PROXY_REDIRECT_STATUS)
        return await call_next(request)

import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch

from fastapi import HTTPException
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.nodes.proxy import NodeUiProxy
from app.nodes.proxy import build_node_ui_proxy_router
from app.reverse_proxy import ReverseProxyService


class _FakeNodeProxy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.websocket_calls: list[tuple[str, str, str]] = []
        self.api_calls: list[tuple[str, str, str]] = []

    async def forward(self, request: Request, node_id: str, path: str = "", *, public_prefix: str = "") -> JSONResponse:
        self.calls.append((request.method, node_id, path, public_prefix))
        return JSONResponse(
            {
                "method": request.method,
                "node_id": node_id,
                "path": path,
                "public_prefix": public_prefix,
            }
        )

    async def forward_websocket(self, websocket, node_id: str, path: str = "", *, public_prefix: str = "") -> None:
        self.websocket_calls.append((node_id, path, public_prefix))
        await websocket.accept()
        await websocket.send_text(f"{node_id}:{path}:{public_prefix}")
        await websocket.close()

    async def forward_api(self, request: Request, node_id: str, path: str = "") -> JSONResponse:
        self.api_calls.append((request.method, node_id, path))
        return JSONResponse({"method": request.method, "node_id": node_id, "path": path})


class TestNodeUiProxyRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict("os.environ", {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False)
        self.env_patch.start()
        self.proxy = _FakeNodeProxy()
        app = FastAPI()
        app.include_router(build_node_ui_proxy_router(self.proxy))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env_patch.stop()

    def test_node_ui_routes_forward(self) -> None:
        checks = [
            ("/nodes/node-1/ui/", ""),
            ("/nodes/node-1/ui/assets/main.js", "assets/main.js"),
            ("/ui/nodes/node-1", ""),
            ("/ui/nodes/node-1/assets/main.js", "assets/main.js"),
        ]

        for url, expected_path in checks:
            resp = self.client.get(url, headers={"X-Admin-Token": "test-token"})
            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertEqual(payload["node_id"], "node-1")
            self.assertEqual(payload["path"], expected_path)
            self.assertTrue(payload["public_prefix"].startswith("/"))

        self.assertEqual(
            self.proxy.calls,
            [
                ("GET", "node-1", "", "/nodes/node-1/ui"),
                ("GET", "node-1", "assets/main.js", "/nodes/node-1/ui"),
                ("GET", "node-1", "", "/ui/nodes/node-1"),
                ("GET", "node-1", "assets/main.js", "/ui/nodes/node-1"),
            ],
        )

    def test_node_ui_routes_remain_get_head_only(self) -> None:
        denied = self.client.post("/nodes/node-1/ui/", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(denied.status_code, 405, denied.text)

        head = self.client.head("/nodes/node-1/ui/status", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(head.status_code, 200, head.text)

        self.assertEqual(self.proxy.calls, [("HEAD", "node-1", "status", "/nodes/node-1/ui")])

    def test_node_ui_websocket_routes_forward(self) -> None:
        with self.client.websocket_connect("/nodes/node-1/ui/ws", headers={"X-Admin-Token": "test-token"}) as ws:
            self.assertEqual(ws.receive_text(), "node-1:ws:/nodes/node-1/ui")

        with self.client.websocket_connect("/ui/nodes/node-1/live", headers={"X-Admin-Token": "test-token"}) as ws:
            self.assertEqual(ws.receive_text(), "node-1:live:/ui/nodes/node-1")

        self.assertEqual(
            self.proxy.websocket_calls,
            [
                ("node-1", "ws", "/nodes/node-1/ui"),
                ("node-1", "live", "/ui/nodes/node-1"),
            ],
        )

    def test_node_api_proxy_routes_forward(self) -> None:
        checks = [
            ("GET", "/api/nodes/node-1/status", "status"),
            ("POST", "/api/nodes/node-1/v1/infer", "v1/infer"),
            ("GET", "/api/nodes/node-1/", ""),
        ]
        for method, url, expected_path in checks:
            resp = self.client.request(method, url, headers={"X-Admin-Token": "test-token"})
            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertEqual(payload["node_id"], "node-1")
            self.assertEqual(payload["path"], expected_path)

        self.assertEqual(
            self.proxy.api_calls,
            [
                ("GET", "node-1", "status"),
                ("POST", "node-1", "v1/infer"),
                ("GET", "node-1", ""),
            ],
        )

    def test_proxy_routes_require_admin_auth(self) -> None:
        denied = self.client.get("/nodes/node-1/ui/")
        self.assertEqual(denied.status_code, 401, denied.text)

    def test_websocket_proxy_requires_admin_auth(self) -> None:
        with self.assertRaises(WebSocketDisconnect) as exc:
            with self.client.websocket_connect("/nodes/node-1/ui/ws"):
                pass
        self.assertEqual(exc.exception.code, 4401)


class TestNodeUiProxyHtmlRewrite(unittest.TestCase):
    def test_build_target_url_preserves_vite_paths(self) -> None:
        target = ReverseProxyService.build_target_url(
            "http://10.0.0.100:8081",
            "@vite/client",
            "t=123",
        )
        self.assertEqual(target, "http://10.0.0.100:8081/@vite/client?t=123")

    def test_rewrites_root_absolute_html_urls_to_proxy_prefix(self) -> None:
        original = b"""
        <!doctype html>
        <html>
          <head>
            <script type="module">import { injectIntoGlobalHook } from "/@react-refresh";</script>
            <script type="module" src="/@vite/client"></script>
            <link rel="stylesheet" href="/src/index.css" />
          </head>
          <body>
            <form action="/submit"></form>
            <img src="/logo.svg" />
            <script>window.__status = "/api/node/status";</script>
          </body>
        </html>
        """

        rewritten = NodeUiProxy._rewrite_root_urls(
            original,
            "text/html; charset=utf-8",
            public_prefix="/nodes/node-123/ui",
            api_public_prefix="/api/nodes/node-123",
        ).decode("utf-8")

        self.assertIn('from "/nodes/node-123/ui/@react-refresh"', rewritten)
        self.assertIn('src="/nodes/node-123/ui/@vite/client"', rewritten)
        self.assertIn('href="/nodes/node-123/ui/src/index.css"', rewritten)
        self.assertIn('action="/nodes/node-123/ui/submit"', rewritten)
        self.assertIn('src="/nodes/node-123/ui/logo.svg"', rewritten)
        self.assertIn('"/api/nodes/node-123/node/status"', rewritten)

    def test_leaves_non_html_responses_unchanged(self) -> None:
        original = b'{"ok":true,"path":"/status"}'
        rewritten = NodeUiProxy._rewrite_root_urls(
            original,
            "application/json",
            public_prefix="/nodes/node-123/ui",
            api_public_prefix="/api/nodes/node-123",
        )
        self.assertEqual(rewritten, original)

    def test_rewrites_root_absolute_javascript_imports(self) -> None:
        original = b"""
        import "/node_modules/vite/dist/client/env.mjs";
        import App from "/src/App.jsx?t=123";
        import "/src/theme/index.css";
        """

        rewritten = NodeUiProxy._rewrite_root_urls(
            original,
            "text/javascript",
            public_prefix="/nodes/node-123/ui",
            api_public_prefix="/api/nodes/node-123",
        ).decode("utf-8")

        self.assertIn('"/nodes/node-123/ui/node_modules/vite/dist/client/env.mjs"', rewritten)
        self.assertIn('"/nodes/node-123/ui/src/App.jsx?t=123"', rewritten)
        self.assertIn('"/nodes/node-123/ui/src/theme/index.css"', rewritten)

    def test_rewrites_root_absolute_javascript_api_calls_to_node_api_proxy(self) -> None:
        original = b"""
        const statusPath = "/api/node/status";
        const absoluteApi = "/api/v1/models";
        """

        rewritten = NodeUiProxy._rewrite_root_urls(
            original,
            "text/javascript",
            public_prefix="/nodes/node-123/ui",
            api_public_prefix="/api/nodes/node-123",
        ).decode("utf-8")

        self.assertIn('"/api/nodes/node-123/node/status"', rewritten)
        self.assertIn('"/api/nodes/node-123/v1/models"', rewritten)


class _TargetService:
    def __init__(self, node) -> None:
        self._node = node

    def get_node(self, node_id: str):
        if node_id != "node-1":
            raise HTTPException(status_code=404, detail="node_not_found")
        return self._node


class TestNodeUiProxyTargetSelection(unittest.TestCase):
    def test_uses_canonical_ui_base_url(self) -> None:
        proxy = NodeUiProxy(
            _TargetService(
                type(
                    "Node",
                    (),
                    {
                        "ui_enabled": True,
                        "ui_base_url": "http://10.0.0.9:8765/ui",
                    },
                )()
            )
        )
        request = type("Req", (), {"url": type("Url", (), {"scheme": "http"})()})()
        self.assertEqual(proxy._target_base("node-1", request), "http://10.0.0.9:8765/ui")

    def test_api_target_base_uses_canonical_node_api_base_url(self) -> None:
        proxy = NodeUiProxy(
            _TargetService(
                type(
                    "Node",
                    (),
                    {
                        "ui_enabled": True,
                        "ui_base_url": "http://10.0.0.9:8765/ui",
                        "api_base_url": "http://10.0.0.9:8081",
                    },
                )()
            )
        )
        request = type("Req", (), {"url": type("Url", (), {"scheme": "http"})()})()
        self.assertEqual(proxy._api_target_base("node-1", request), "http://10.0.0.9:8081")

    def test_api_target_base_falls_back_to_node_ui_origin_for_legacy_metadata(self) -> None:
        proxy = NodeUiProxy(
            _TargetService(
                type(
                    "Node",
                    (),
                    {
                        "ui_enabled": True,
                        "ui_base_url": "http://10.0.0.9:8765/ui",
                        "api_base_url": None,
                        "requested_ui_endpoint": "http://10.0.0.9:8765/ui",
                        "requested_hostname": "10.0.0.9:8765",
                    },
                )()
            )
        )
        request = type("Req", (), {"url": type("Url", (), {"scheme": "http"})()})()
        self.assertEqual(proxy._api_target_base("node-1", request), "http://10.0.0.9:8765")

    def test_rejects_disabled_node_ui(self) -> None:
        proxy = NodeUiProxy(
            _TargetService(
                type(
                    "Node",
                    (),
                    {
                        "ui_enabled": False,
                        "ui_base_url": "http://10.0.0.9:8765/ui",
                    },
                )()
            )
        )
        request = type("Req", (), {"url": type("Url", (), {"scheme": "http"})()})()
        with self.assertRaises(HTTPException) as exc:
            proxy._target_base("node-1", request)
        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(exc.exception.detail, "node_ui_not_enabled")

    def test_rejects_missing_node_ui_base_url(self) -> None:
        proxy = NodeUiProxy(
            _TargetService(
                type(
                    "Node",
                    (),
                    {
                        "ui_enabled": True,
                        "ui_base_url": None,
                    },
                )()
            )
        )
        request = type("Req", (), {"url": type("Url", (), {"scheme": "http"})()})()
        with self.assertRaises(HTTPException) as exc:
            proxy._target_base("node-1", request)
        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(exc.exception.detail, "node_ui_endpoint_not_configured")

    def test_rejects_prefix_incompatible_node_ui(self) -> None:
        proxy = NodeUiProxy(
            _TargetService(
                type(
                    "Node",
                    (),
                    {
                        "ui_enabled": True,
                        "ui_base_url": "http://10.0.0.9:8765/ui",
                        "ui_supports_prefix": False,
                    },
                )()
            )
        )
        request = type("Req", (), {"url": type("Url", (), {"scheme": "http"})()})()
        with self.assertRaises(HTTPException) as exc:
            proxy._target_base("node-1", request)
        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(exc.exception.detail, "node_ui_prefix_not_supported")

    def test_ui_route_returns_html_error_page_when_ui_disabled(self) -> None:
        proxy = NodeUiProxy(
            _TargetService(
                type(
                    "Node",
                    (),
                    {
                        "ui_enabled": False,
                        "ui_base_url": "http://10.0.0.9:8765/ui",
                    },
                )()
            )
        )
        app = FastAPI()
        app.include_router(build_node_ui_proxy_router(proxy))
        with patch.dict("os.environ", {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False):
            client = TestClient(app)
            response = client.get("/nodes/node-1/ui/", headers={"X-Admin-Token": "test-token"})
            self.assertEqual(response.status_code, 404, response.text)
            self.assertIn("Node UI Unavailable", response.text)
            self.assertIn("node_ui_not_enabled", response.text)

    def test_ui_route_returns_html_error_page_when_health_probe_fails(self) -> None:
        proxy = NodeUiProxy(
            _TargetService(
                type(
                    "Node",
                    (),
                    {
                        "ui_enabled": True,
                        "ui_base_url": "http://10.0.0.9:8765/ui",
                        "ui_health_endpoint": "http://10.0.0.9:8765/health",
                    },
                )()
            )
        )
        proxy._proxy.probe_health = AsyncMock(return_value=(False, "health_probe_status_unhealthy"))
        app = FastAPI()
        app.include_router(build_node_ui_proxy_router(proxy))
        with patch.dict("os.environ", {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False):
            client = TestClient(app)
            response = client.get("/nodes/node-1/ui/", headers={"X-Admin-Token": "test-token"})
            self.assertEqual(response.status_code, 503, response.text)
            self.assertIn("Node UI Unavailable", response.text)
            self.assertIn("health_probe_status_unhealthy", response.text)

    def test_ui_route_emits_proxy_log_entry(self) -> None:
        proxy = NodeUiProxy(
            _TargetService(
                type(
                    "Node",
                    (),
                    {
                        "ui_enabled": False,
                        "ui_base_url": "http://10.0.0.9:8765/ui",
                    },
                )()
            )
        )
        app = FastAPI()
        app.include_router(build_node_ui_proxy_router(proxy))
        with patch.dict("os.environ", {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False):
            client = TestClient(app)
            with self.assertLogs("synthia.proxy", level="INFO") as captured:
                client.get("/nodes/node-1/ui/", headers={"X-Admin-Token": "test-token"})
        self.assertTrue(any("surface=ui" in message and "node_id=node-1" in message for message in captured.output))


if __name__ == "__main__":
    unittest.main()

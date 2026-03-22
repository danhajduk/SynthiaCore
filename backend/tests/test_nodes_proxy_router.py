import unittest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.nodes.proxy import NodeUiProxy
from app.nodes.proxy import build_node_ui_proxy_router


class _FakeNodeProxy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def forward(self, request: Request, node_id: str, path: str = "") -> JSONResponse:
        self.calls.append((request.method, node_id, path))
        return JSONResponse(
            {
                "method": request.method,
                "node_id": node_id,
                "path": path,
            }
        )


class TestNodeUiProxyRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.proxy = _FakeNodeProxy()
        app = FastAPI()
        app.include_router(build_node_ui_proxy_router(self.proxy))
        self.client = TestClient(app)

    def test_node_ui_routes_forward(self) -> None:
        checks = [
            ("/ui/nodes/node-1", ""),
            ("/ui/nodes/node-1/assets/main.js", "assets/main.js"),
        ]

        for url, expected_path in checks:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertEqual(payload["node_id"], "node-1")
            self.assertEqual(payload["path"], expected_path)

        self.assertEqual(
            self.proxy.calls,
            [
                ("GET", "node-1", ""),
                ("GET", "node-1", "assets/main.js"),
            ],
        )

    def test_node_ui_routes_remain_get_head_only(self) -> None:
        denied = self.client.post("/ui/nodes/node-1")
        self.assertEqual(denied.status_code, 405, denied.text)

        head = self.client.head("/ui/nodes/node-1/status")
        self.assertEqual(head.status_code, 200, head.text)

        self.assertEqual(self.proxy.calls, [("HEAD", "node-1", "status")])


class TestNodeUiProxyHtmlRewrite(unittest.TestCase):
    def test_build_target_url_preserves_vite_paths(self) -> None:
        target = NodeUiProxy._build_target_url(
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
          </body>
        </html>
        """

        rewritten = NodeUiProxy._rewrite_root_urls(
            original,
            "text/html; charset=utf-8",
            "node-123",
        ).decode("utf-8")

        self.assertIn('from "/ui/nodes/node-123/@react-refresh"', rewritten)
        self.assertIn('src="/ui/nodes/node-123/@vite/client"', rewritten)
        self.assertIn('href="/ui/nodes/node-123/src/index.css"', rewritten)
        self.assertIn('action="/ui/nodes/node-123/submit"', rewritten)
        self.assertIn('src="/ui/nodes/node-123/logo.svg"', rewritten)

    def test_leaves_non_html_responses_unchanged(self) -> None:
        original = b'{"ok":true,"path":"/status"}'
        rewritten = NodeUiProxy._rewrite_root_urls(
            original,
            "application/json",
            "node-123",
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
            "node-123",
        ).decode("utf-8")

        self.assertIn('"/ui/nodes/node-123/node_modules/vite/dist/client/env.mjs"', rewritten)
        self.assertIn('"/ui/nodes/node-123/src/App.jsx?t=123"', rewritten)
        self.assertIn('"/ui/nodes/node-123/src/theme/index.css"', rewritten)


if __name__ == "__main__":
    unittest.main()

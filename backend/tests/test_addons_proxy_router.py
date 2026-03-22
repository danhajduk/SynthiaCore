import unittest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.addons.proxy import build_proxy_router


class _FakeProxy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.websocket_calls: list[tuple[str, str, str]] = []
        self.api_calls: list[tuple[str, str, str]] = []

    async def forward_ui(self, request: Request, addon_id: str, path: str = "", *, public_prefix: str = "") -> JSONResponse:
        self.calls.append((request.method, addon_id, path, public_prefix))
        return JSONResponse(
            {
                "method": request.method,
                "addon_id": addon_id,
                "path": path,
                "public_prefix": public_prefix,
            }
        )

    async def forward_api(self, request: Request, addon_id: str, path: str = "") -> JSONResponse:
        self.api_calls.append((request.method, addon_id, path))
        return JSONResponse({"method": request.method, "addon_id": addon_id, "path": path})

    async def forward_websocket(self, websocket, addon_id: str, path: str = "", *, public_prefix: str = "") -> None:
        self.websocket_calls.append((addon_id, path, public_prefix))
        await websocket.accept()
        await websocket.send_text(f"{addon_id}:{path}:{public_prefix}")
        await websocket.close()


class TestAddonsProxyRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.proxy = _FakeProxy()
        app = FastAPI()
        app.include_router(build_proxy_router(self.proxy))
        self.client = TestClient(app)

    def test_ui_legacy_and_canonical_routes_forward(self) -> None:
        checks = [
            ("/addons/mqtt/", ""),
            ("/addons/mqtt/assets/main.js", "assets/main.js"),
            ("/ui/addons/mqtt", ""),
            ("/ui/addons/mqtt/assets/main.js", "assets/main.js"),
        ]

        for url, expected_path in checks:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertEqual(payload["addon_id"], "mqtt")
            self.assertEqual(payload["path"], expected_path)
            self.assertTrue(payload["public_prefix"].startswith("/"))

        self.assertEqual(
            self.proxy.calls,
            [
                ("GET", "mqtt", "", "/addons/mqtt"),
                ("GET", "mqtt", "assets/main.js", "/addons/mqtt"),
                ("GET", "mqtt", "", "/ui/addons/mqtt"),
                ("GET", "mqtt", "assets/main.js", "/ui/addons/mqtt"),
            ],
        )

    def test_canonical_routes_remain_get_head_only(self) -> None:
        denied = self.client.post("/addons/mqtt/")
        self.assertEqual(denied.status_code, 405, denied.text)

        head = self.client.head("/addons/mqtt/status")
        self.assertEqual(head.status_code, 200, head.text)

        self.assertEqual(self.proxy.calls, [("HEAD", "mqtt", "status", "/addons/mqtt")])

    def test_websocket_routes_forward(self) -> None:
        with self.client.websocket_connect("/addons/mqtt/ws") as ws:
            self.assertEqual(ws.receive_text(), "mqtt:ws:/addons/mqtt")

        with self.client.websocket_connect("/ui/addons/mqtt/live") as ws:
            self.assertEqual(ws.receive_text(), "mqtt:live:/ui/addons/mqtt")

        self.assertEqual(
            self.proxy.websocket_calls,
            [
                ("mqtt", "ws", "/addons/mqtt"),
                ("mqtt", "live", "/ui/addons/mqtt"),
            ],
        )

    def test_api_proxy_routes_forward(self) -> None:
        checks = [
            ("GET", "/api/addons/mqtt/status", "status"),
            ("POST", "/api/addons/mqtt/v1/run", "v1/run"),
            ("GET", "/api/addons/mqtt", ""),
        ]
        for method, url, expected_path in checks:
            resp = self.client.request(method, url)
            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertEqual(payload["addon_id"], "mqtt")
            self.assertEqual(payload["path"], expected_path)

        self.assertEqual(
            self.proxy.api_calls,
            [
                ("GET", "mqtt", "status"),
                ("POST", "mqtt", "v1/run"),
                ("GET", "mqtt", ""),
            ],
        )


if __name__ == "__main__":
    unittest.main()

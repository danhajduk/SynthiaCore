import unittest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.addons.proxy import build_proxy_router


class _FakeProxy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def forward(self, request: Request, addon_id: str, path: str = "") -> JSONResponse:
        self.calls.append((request.method, addon_id, path))
        return JSONResponse(
            {
                "method": request.method,
                "addon_id": addon_id,
                "path": path,
            }
        )


class TestAddonsProxyRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.proxy = _FakeProxy()
        app = FastAPI()
        app.include_router(build_proxy_router(self.proxy))
        self.client = TestClient(app)

    def test_ui_legacy_and_alias_routes_forward(self) -> None:
        checks = [
            ("/ui/addons/mqtt", ""),
            ("/ui/addons/mqtt/assets/main.js", "assets/main.js"),
            ("/addons/mqtt", ""),
            ("/addons/mqtt/assets/main.js", "assets/main.js"),
        ]

        for url, expected_path in checks:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertEqual(payload["addon_id"], "mqtt")
            self.assertEqual(payload["path"], expected_path)

        self.assertEqual(
            self.proxy.calls,
            [
                ("GET", "mqtt", ""),
                ("GET", "mqtt", "assets/main.js"),
                ("GET", "mqtt", ""),
                ("GET", "mqtt", "assets/main.js"),
            ],
        )

    def test_alias_routes_remain_get_head_only(self) -> None:
        denied = self.client.post("/addons/mqtt")
        self.assertEqual(denied.status_code, 405, denied.text)

        head = self.client.head("/addons/mqtt/status")
        self.assertEqual(head.status_code, 200, head.text)

        self.assertEqual(self.proxy.calls, [("HEAD", "mqtt", "status")])


if __name__ == "__main__":
    unittest.main()

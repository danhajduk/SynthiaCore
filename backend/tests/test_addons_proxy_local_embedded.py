import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from app.addons.proxy import AddonProxy, build_proxy_router


class _FakeRegistry:
    def __init__(self) -> None:
        self.registered = {}
        self.addons = {"mqtt": object()}


class TestAddonsProxyLocalEmbedded(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(os.environ, {}, clear=False)
        self.env_patch.start()
        self.proxy = AddonProxy(_FakeRegistry())
        app = FastAPI()

        @app.get("/api/addons/mqtt", response_class=HTMLResponse)
        async def mqtt_ui_root():
            return "<html><body>mqtt local ui</body></html>"

        app.include_router(build_proxy_router(self.proxy))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env_patch.stop()

    def test_ui_proxy_uses_local_embedded_target(self) -> None:
        upstream = httpx.Response(200, headers={"content-type": "text/html"}, text="<html>mqtt</html>")
        with patch.object(self.proxy._client, "request", new=AsyncMock(return_value=upstream)) as request_mock:
            res = self.client.get("/ui/addons/mqtt")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("mqtt", res.text)
        kwargs = request_mock.await_args.kwargs
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(kwargs["url"], "http://testserver/api/addons/mqtt")

    def test_alias_proxy_uses_local_embedded_target(self) -> None:
        upstream = httpx.Response(200, headers={"content-type": "text/html"}, text="<html>mqtt alias</html>")
        with patch.object(self.proxy._client, "request", new=AsyncMock(return_value=upstream)) as request_mock:
            res = self.client.get("/addons/mqtt")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("mqtt", res.text)
        kwargs = request_mock.await_args.kwargs
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(kwargs["url"], "http://testserver/api/addons/mqtt")

    def test_missing_addon_still_returns_not_found(self) -> None:
        res = self.client.get("/ui/addons/missing")
        self.assertEqual(res.status_code, 404, res.text)
        self.assertEqual(res.json()["detail"], "registered_addon_not_found")


if __name__ == "__main__":
    unittest.main()

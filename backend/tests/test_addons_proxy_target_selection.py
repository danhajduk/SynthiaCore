import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.addons.models import RegisteredAddon
from app.addons.proxy import AddonProxy, build_proxy_router


class _FakeRegistry:
    def __init__(self, addon: RegisteredAddon | None = None) -> None:
        self.registered = {}
        if addon is not None:
            self.registered[addon.id] = addon
        self.addons = {}


class TestAddonProxyTargetSelection(unittest.TestCase):
    def test_ui_target_base_uses_canonical_ui_base_url(self) -> None:
        proxy = AddonProxy(
            _FakeRegistry(
                RegisteredAddon(
                    id="mqtt",
                    name="MQTT",
                    version="0.1.0",
                    base_url="http://127.0.0.1:9100/api",
                    ui_enabled=True,
                    ui_base_url="http://127.0.0.1:9100/ui",
                    ui_mode="server",
                )
            )
        )
        request = type("Req", (), {"base_url": "http://core.local:9001/"})()
        self.assertEqual(proxy._ui_target_base("mqtt", request), "http://127.0.0.1:9100/ui")

    def test_api_target_base_uses_registered_base_url(self) -> None:
        proxy = AddonProxy(
            _FakeRegistry(
                RegisteredAddon(
                    id="mqtt",
                    name="MQTT",
                    version="0.1.0",
                    base_url="http://127.0.0.1:9100/api",
                    ui_enabled=True,
                    ui_base_url="http://127.0.0.1:9100/ui",
                    ui_mode="server",
                )
            )
        )
        request = type("Req", (), {"base_url": "http://core.local:9001/"})()
        self.assertEqual(proxy._api_target_base("mqtt", request), "http://127.0.0.1:9100/api")

    def test_ui_target_rejects_disabled_ui(self) -> None:
        proxy = AddonProxy(
            _FakeRegistry(
                RegisteredAddon(
                    id="mqtt",
                    name="MQTT",
                    version="0.1.0",
                    base_url="http://127.0.0.1:9100/api",
                    ui_enabled=False,
                    ui_base_url="http://127.0.0.1:9100/ui",
                    ui_mode="server",
                )
            )
        )
        request = type("Req", (), {"base_url": "http://core.local:9001/"})()
        with self.assertRaises(HTTPException) as exc:
            proxy._ui_target_base("mqtt", request)
        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(exc.exception.detail, "addon_ui_not_enabled")

    def test_rewrites_root_absolute_html_urls_to_proxy_prefix(self) -> None:
        original = b"""
        <!doctype html>
        <html>
          <head>
            <script type="module" src="/@vite/client"></script>
            <link rel="stylesheet" href="/src/index.css" />
          </head>
          <body>
            <form action="/submit"></form>
            <img src="/logo.svg" />
          </body>
        </html>
        """

        rewritten = AddonProxy._rewrite_root_urls(
            original,
            "text/html; charset=utf-8",
            public_prefix="/addons/mqtt",
        ).decode("utf-8")

        self.assertIn('src="/addons/mqtt/@vite/client"', rewritten)
        self.assertIn('href="/addons/mqtt/src/index.css"', rewritten)
        self.assertIn('action="/addons/mqtt/submit"', rewritten)
        self.assertIn('src="/addons/mqtt/logo.svg"', rewritten)

    def test_rewrites_root_absolute_javascript_imports_to_proxy_prefix(self) -> None:
        original = b"""
        import "/src/main.ts";
        import "/src/theme/index.css";
        """

        rewritten = AddonProxy._rewrite_root_urls(
            original,
            "text/javascript",
            public_prefix="/ui/addons/mqtt",
        ).decode("utf-8")

        self.assertIn('"/ui/addons/mqtt/src/main.ts"', rewritten)
        self.assertIn('"/ui/addons/mqtt/src/theme/index.css"', rewritten)

    def test_ui_route_returns_html_error_page_when_ui_disabled(self) -> None:
        proxy = AddonProxy(
            _FakeRegistry(
                RegisteredAddon(
                    id="mqtt",
                    name="MQTT",
                    version="0.1.0",
                    base_url="http://127.0.0.1:9100/api",
                    ui_enabled=False,
                    ui_base_url="http://127.0.0.1:9100/ui",
                    ui_mode="server",
                )
            )
        )
        app = FastAPI()
        app.include_router(build_proxy_router(proxy))
        with patch.dict("os.environ", {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False):
            client = TestClient(app)
            response = client.get("/addons/mqtt/", headers={"X-Admin-Token": "test-token"})
            self.assertEqual(response.status_code, 404, response.text)
            self.assertIn("Addon UI Unavailable", response.text)
            self.assertIn("addon_ui_not_enabled", response.text)

    def test_ui_route_returns_html_error_page_when_addon_health_is_unhealthy(self) -> None:
        proxy = AddonProxy(
            _FakeRegistry(
                RegisteredAddon(
                    id="mqtt",
                    name="MQTT",
                    version="0.1.0",
                    base_url="http://127.0.0.1:9100/api",
                    ui_enabled=True,
                    ui_base_url="http://127.0.0.1:9100/ui",
                    ui_mode="server",
                    health_status="unhealthy",
                )
            )
        )
        app = FastAPI()
        app.include_router(build_proxy_router(proxy))
        with patch.dict("os.environ", {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False):
            client = TestClient(app)
            response = client.get("/addons/mqtt/", headers={"X-Admin-Token": "test-token"})
            self.assertEqual(response.status_code, 503, response.text)
            self.assertIn("Addon UI Unavailable", response.text)
            self.assertIn("addon_health_unhealthy", response.text)

    def test_ui_route_emits_proxy_log_entry(self) -> None:
        proxy = AddonProxy(_FakeRegistry())
        app = FastAPI()
        app.include_router(build_proxy_router(proxy))
        with patch.dict("os.environ", {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False):
            client = TestClient(app)
            with self.assertLogs("synthia.proxy", level="INFO") as captured:
                client.get("/ui/addons/missing", headers={"X-Admin-Token": "test-token"})
        self.assertTrue(any("surface=ui" in message and "addon_id=missing" in message for message in captured.output))


if __name__ == "__main__":
    unittest.main()

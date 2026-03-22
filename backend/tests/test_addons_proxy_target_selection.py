import unittest

from fastapi import HTTPException

from app.addons.models import RegisteredAddon
from app.addons.proxy import AddonProxy


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


if __name__ == "__main__":
    unittest.main()

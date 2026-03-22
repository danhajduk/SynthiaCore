import unittest

from fastapi import HTTPException

from app.ui_target_resolver import UiTargetResolver


class _AddonRegistry:
    def __init__(self, *, registered=None, embedded=None) -> None:
        self.registered = registered or {}
        self.addons = embedded or {}


class _NodesService:
    def __init__(self, node) -> None:
        self._node = node

    def get_node(self, node_id: str):
        if node_id != "node-1":
            raise HTTPException(status_code=404, detail="node_not_found")
        return self._node


class TestUiTargetResolver(unittest.TestCase):
    def test_resolves_registered_addon_ui_target(self) -> None:
        addon = type(
            "Addon",
            (),
            {
                "ui_enabled": True,
                "ui_base_url": "http://127.0.0.1:9100/ui",
                "base_url": "http://127.0.0.1:9100/api",
            },
        )()
        resolver = UiTargetResolver(addon_registry=_AddonRegistry(registered={"mqtt": addon}))
        resolved = resolver.resolve_addon_ui("mqtt", request_base_url="http://core.local:9001/")
        self.assertEqual(resolved.source, "registered_remote")
        self.assertEqual(resolved.public_prefix, "/addons/mqtt")
        self.assertEqual(resolved.target_base, "http://127.0.0.1:9100/ui")

    def test_resolves_embedded_addon_ui_target(self) -> None:
        resolver = UiTargetResolver(addon_registry=_AddonRegistry(embedded={"mqtt": object()}))
        resolved = resolver.resolve_addon_ui("mqtt", request_base_url="http://core.local:9001/")
        self.assertEqual(resolved.source, "embedded_local")
        self.assertEqual(resolved.target_base, "http://core.local:9001/api/addons/mqtt")

    def test_rejects_prefix_incompatible_addon(self) -> None:
        addon = type(
            "Addon",
            (),
            {
                "ui_enabled": True,
                "ui_base_url": "http://127.0.0.1:9100/ui",
                "ui_supports_prefix": False,
                "base_url": "http://127.0.0.1:9100/api",
            },
        )()
        resolver = UiTargetResolver(addon_registry=_AddonRegistry(registered={"mqtt": addon}))
        with self.assertRaises(HTTPException) as exc:
            resolver.resolve_addon_ui("mqtt", request_base_url="http://core.local:9001/")
        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(exc.exception.detail, "addon_ui_prefix_not_supported")

    def test_resolves_node_ui_and_api_targets(self) -> None:
        node = type(
            "Node",
            (),
            {
                "ui_enabled": True,
                "ui_base_url": "http://10.0.0.9:8765/ui",
                "ui_health_endpoint": "http://10.0.0.9:8765/health",
                "api_base_url": "http://10.0.0.9:8081",
            },
        )()
        resolver = UiTargetResolver(nodes_service=_NodesService(node))
        ui_target = resolver.resolve_node_ui("node-1")
        api_target = resolver.resolve_node_api("node-1")
        self.assertEqual(ui_target.public_prefix, "/nodes/node-1/ui")
        self.assertEqual(ui_target.health_endpoint, "http://10.0.0.9:8765/health")
        self.assertEqual(api_target.public_prefix, "/api/nodes/node-1")
        self.assertEqual(api_target.target_base, "http://10.0.0.9:8765")


if __name__ == "__main__":
    unittest.main()

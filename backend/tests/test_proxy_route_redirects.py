import unittest

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from app.proxy_routes import ProxyRouteRedirectMiddleware


class TestProxyRouteRedirectMiddleware(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.add_middleware(ProxyRouteRedirectMiddleware)

        @app.get("/addons/proxy/{addon_id}/")
        async def addon_root(addon_id: str):
            return PlainTextResponse(f"addon:{addon_id}")

        @app.get("/nodes/proxy/{node_id}/")
        async def node_root(node_id: str):
            return PlainTextResponse(f"node:{node_id}")

        @app.get("/nodes/proxy/ui/{node_id}/{path:path}")
        async def node_ui_navigation_path(node_id: str, path: str):
            return PlainTextResponse(f"node-ui:{node_id}:{path}")

        @app.get("/nodes/proxy/{node_id}/{path:path}")
        async def node_path(node_id: str, path: str):
            return PlainTextResponse(f"node:{node_id}:{path}")

        @app.get("/addons/proxy/{addon_id}/{path:path}")
        async def addon_path(addon_id: str, path: str):
            return PlainTextResponse(f"addon:{addon_id}:{path}")

        self.client = TestClient(app)

    def test_redirects_legacy_node_ui_routes_to_canonical_paths(self) -> None:
        response = self.client.get("/ui/nodes/node-1/assets/main.js", follow_redirects=False)
        self.assertEqual(response.status_code, 307, response.text)
        self.assertEqual(response.headers["location"], "/nodes/proxy/ui/node-1/assets/main.js")

    def test_redirects_legacy_addon_ui_routes_to_canonical_paths(self) -> None:
        response = self.client.get("/ui/addons/mqtt?view=full", follow_redirects=False)
        self.assertEqual(response.status_code, 307, response.text)
        self.assertEqual(response.headers["location"], "/addons/proxy/mqtt/?view=full")

    def test_redirects_canonical_roots_to_trailing_slash_variants(self) -> None:
        addon = self.client.get("/addons/proxy/mqtt", follow_redirects=False)
        self.assertEqual(addon.status_code, 307, addon.text)
        self.assertEqual(addon.headers["location"], "/addons/proxy/mqtt/")

        node = self.client.get("/nodes/proxy/node-1", follow_redirects=False)
        self.assertEqual(node.status_code, 307, node.text)
        self.assertEqual(node.headers["location"], "/nodes/proxy/node-1/")

    def test_leaves_nodes_proxy_ui_alias_untouched(self) -> None:
        response = self.client.get("/nodes/proxy/ui/node-1/google/gmail/callback", follow_redirects=False)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.text, "node-ui:node-1:google/gmail/callback")


if __name__ == "__main__":
    unittest.main()

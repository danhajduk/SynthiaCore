import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from websockets.sync.server import serve

from app.addons.models import RegisteredAddon
from app.addons.proxy import AddonProxy, build_proxy_router
from app.nodes.proxy import NodeUiProxy, build_node_ui_proxy_router


class _EchoServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []
        self._server_cm = None
        self._server = None
        self._thread: threading.Thread | None = None
        self.port: int | None = None

    def __enter__(self) -> "_EchoServer":
        def handler(connection) -> None:
            for message in connection:
                connection.send(message)

        def process_request(_connection, request):
            self.requests.append(dict(request.headers))
            return None

        self._server_cm = serve(
            handler,
            "127.0.0.1",
            0,
            process_request=process_request,
            subprotocols=["chat"],
        )
        self._server = self._server_cm.__enter__()
        self.port = int(self._server.socket.getsockname()[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self._server is not None
        assert self._server_cm is not None
        self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server_cm.__exit__(exc_type, exc, tb)


class _FakeAddonRegistry:
    def __init__(self, base_url: str) -> None:
        self.registered = {
            "mqtt": RegisteredAddon(
                id="mqtt",
                name="Hexe MQTT",
                version="0.1.0",
                base_url=base_url,
                ui_enabled=True,
                ui_base_url=base_url,
                ui_mode="server",
            )
        }
        self.addons = {}


class _FakeNodesService:
    def __init__(self, endpoint: str) -> None:
        self._node = SimpleNamespace(ui_enabled=True, ui_base_url=endpoint)

    def get_node(self, node_id: str):
        if node_id != "node-1":
            raise KeyError(node_id)
        return self._node


class TestWebSocketProxyIntegration(unittest.TestCase):
    def test_addon_websocket_proxy_round_trip_and_forwarded_headers(self) -> None:
        with patch.dict("os.environ", {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False):
            with _EchoServer() as upstream:
                assert upstream.port is not None
                proxy = AddonProxy(_FakeAddonRegistry(f"http://127.0.0.1:{upstream.port}"))
                app = FastAPI()
                app.include_router(build_proxy_router(proxy))
                client = TestClient(app)

                with client.websocket_connect(
                    "/addons/proxy/mqtt/ws",
                    subprotocols=["chat"],
                    headers={"X-Admin-Token": "test-token"},
                ) as ws:
                    ws.send_text("hello-addon")
                    self.assertEqual(ws.receive_text(), "hello-addon")
                    ws.send_bytes(b"addon-bytes")
                    self.assertEqual(ws.receive_bytes(), b"addon-bytes")

                self.assertTrue(upstream.requests)
                headers = upstream.requests[-1]
                self.assertEqual(headers.get("x-forwarded-prefix"), "/addons/proxy/mqtt")
                self.assertEqual(headers.get("x-hexe-addon-id"), "mqtt")
                self.assertEqual(headers.get("sec-websocket-protocol"), "chat")

    def test_node_websocket_proxy_round_trip_and_forwarded_headers(self) -> None:
        with patch.dict("os.environ", {"SYNTHIA_ADMIN_TOKEN": "test-token"}, clear=False):
            with _EchoServer() as upstream:
                assert upstream.port is not None
                proxy = NodeUiProxy(_FakeNodesService(f"http://127.0.0.1:{upstream.port}"))
                app = FastAPI()
                app.include_router(build_node_ui_proxy_router(proxy))
                client = TestClient(app)

                with client.websocket_connect(
                    "/nodes/proxy/node-1/ws",
                    subprotocols=["chat"],
                    headers={"X-Admin-Token": "test-token"},
                ) as ws:
                    ws.send_text("hello-node")
                    self.assertEqual(ws.receive_text(), "hello-node")
                    ws.send_bytes(b"node-bytes")
                    self.assertEqual(ws.receive_bytes(), b"node-bytes")

                self.assertTrue(upstream.requests)
                headers = upstream.requests[-1]
                self.assertEqual(headers.get("x-forwarded-prefix"), "/nodes/proxy/node-1")
                self.assertEqual(headers.get("x-hexe-node-id"), "node-1")
                self.assertEqual(headers.get("sec-websocket-protocol"), "chat")


if __name__ == "__main__":
    unittest.main()

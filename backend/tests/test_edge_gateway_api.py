import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    FASTAPI_STACK_AVAILABLE = True
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None
    FASTAPI_STACK_AVAILABLE = False

from app.edge import EdgeGatewayService, EdgeGatewayStore, build_edge_router
from app.system.onboarding import NodeRegistrationsStore
from app.system.settings.router import build_settings_router
from app.system.settings.store import SettingsStore
from app.supervisor.service import SupervisorDomainService


class FakeCloudflareClient:
    def __init__(self) -> None:
        self.tunnels: dict[str, dict[str, str]] = {}
        self.dns_records: dict[str, dict[str, object]] = {}
        self.tunnel_counter = 0
        self.dns_counter = 0

    async def find_tunnel_by_name(self, tunnel_name: str):
        for item in self.tunnels.values():
            if item["name"] == tunnel_name:
                return type("Tunnel", (), {"tunnel_id": item["id"], "tunnel_name": item["name"], "created_at": None})()
        return None

    async def get_tunnel(self, tunnel_id: str):
        item = self.tunnels.get(tunnel_id)
        if item is None:
            return None
        return type("Tunnel", (), {"tunnel_id": item["id"], "tunnel_name": item["name"], "created_at": None})()

    async def create_tunnel(self, tunnel_name: str):
        self.tunnel_counter += 1
        tunnel_id = f"tunnel-{self.tunnel_counter}"
        self.tunnels[tunnel_id] = {"id": tunnel_id, "name": tunnel_name}
        return type("Tunnel", (), {"tunnel_id": tunnel_id, "tunnel_name": tunnel_name, "created_at": None})()

    async def get_tunnel_token(self, tunnel_id: str):
        return f"token-{tunnel_id}"

    async def update_tunnel_configuration(self, *, tunnel_id: str, ingress: list[dict[str, object]]):
        return {"tunnel_id": tunnel_id, "version": 1, "config": {"ingress": ingress}, "source": "cloudflare"}

    async def find_dns_record(self, hostname: str):
        record = self.dns_records.get(hostname)
        if record is None:
            return None
        return type(
            "DnsRecord",
            (),
            {
                "record_id": record["id"],
                "name": hostname,
                "content": record["content"],
                "proxied": record["proxied"],
                "type": "CNAME",
            },
        )()

    async def upsert_dns_record(self, *, hostname: str, content: str, proxied: bool = True):
        existing = self.dns_records.get(hostname)
        if existing is None:
            self.dns_counter += 1
            existing = {"id": f"dns-{self.dns_counter}", "content": content, "proxied": proxied}
            self.dns_records[hostname] = existing
        else:
            existing["content"] = content
            existing["proxied"] = proxied
        return type(
            "DnsRecord",
            (),
            {"record_id": existing["id"], "name": hostname, "content": existing["content"], "proxied": existing["proxied"]},
        )()

    async def delete_dns_record(self, record_id: str):
        for hostname, record in list(self.dns_records.items()):
            if record["id"] == record_id:
                self.dns_records.pop(hostname, None)
                break


@unittest.skipIf(not FASTAPI_STACK_AVAILABLE, "fastapi/testclient not available in this environment")
class TestEdgeGatewayApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        base = Path(self.tmpdir.name)
        self.settings = SettingsStore(str(base / "app_settings.db"))
        self.edge_store = EdgeGatewayStore(str(base / "edge_gateway.json"))
        self.registrations = NodeRegistrationsStore(path=base / "node_registrations.json")
        self.supervisor = SupervisorDomainService()
        self.cloudflare = FakeCloudflareClient()
        self.service = EdgeGatewayService(
            self.edge_store,
            settings_store=self.settings,
            node_registrations_store=self.registrations,
            supervisor_service=self.supervisor,
            cloudflare_client_factory=lambda settings: self.cloudflare,
        )
        app = FastAPI()
        app.include_router(build_settings_router(self.settings), prefix="/api/system")
        app.include_router(build_edge_router(self.service), prefix="/api")
        self.client = TestClient(app)
        self.env = patch.dict(
            os.environ,
            {
                "SYNTHIA_ADMIN_TOKEN": "test-token",
                "SYNTHIA_EDGE_RUNTIME_DIR": str(base / "edge-runtime"),
                "SYNTHIA_CLOUDFLARED_PROVIDER": "disabled",
                "CLOUDFLARE_API_TOKEN": "test-cloudflare-token",
                "CLOUDFLARE_ACCOUNT_ID": "acct-env",
                "CLOUDFLARE_ZONE_ID": "zone-env",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmpdir.cleanup()

    def test_public_identity_and_platform_endpoint_share_core_id(self) -> None:
        platform_payload = self.client.get("/api/system/platform").json()
        edge_payload = self.client.get("/api/edge/public-identity").json()
        self.assertEqual(platform_payload["core_id"], edge_payload["core_id"])
        self.assertEqual(platform_payload["public_hostname"], edge_payload["public_hostname"])
        self.assertEqual(platform_payload["public_ui_hostname"], edge_payload["public_ui_hostname"])
        self.assertEqual(platform_payload["public_api_hostname"], edge_payload["public_api_hostname"])
        self.assertEqual(edge_payload["public_hostname"], edge_payload["public_api_hostname"])

    def test_create_publication_and_provision(self) -> None:
        identity = self.client.get("/api/edge/public-identity").json()
        created = self.client.post(
            "/api/edge/publications",
            headers={"X-Admin-Token": "test-token"},
            json={
                "hostname": f"service.{identity['core_id']}.hexe-ai.com",
                "path_prefix": "/mail",
                "enabled": True,
                "source": "operator_defined",
                "target": {
                    "target_type": "local_service",
                    "target_id": "mail-ui",
                    "upstream_base_url": "http://127.0.0.1:8081",
                    "allowed_path_prefixes": ["/mail"],
                },
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        listed = self.client.get("/api/edge/publications")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()["items"]), 5)

        settings_res = self.client.put(
            "/api/edge/cloudflare/settings",
            headers={"X-Admin-Token": "test-token"},
            json={
                "enabled": True,
                "credentials_reference": "/tmp/cloudflare.json",
                "managed_domain_base": "hexe-ai.com",
                "hostname_publication_mode": "core_id_managed",
            },
        )
        self.assertEqual(settings_res.status_code, 200, settings_res.text)

        dry_run = self.client.post("/api/edge/cloudflare/test", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(dry_run.status_code, 200, dry_run.text)
        self.assertTrue(dry_run.json()["ok"])
        self.assertEqual(dry_run.json()["tunnel_name"], f"hexe-core-{identity['core_id']}")

        provisioned = self.client.post("/api/edge/cloudflare/provision", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(provisioned.status_code, 200, provisioned.text)
        self.assertTrue(provisioned.json()["ok"])
        first_tunnel_id = provisioned.json()["provisioning"]["tunnel_id"]
        self.assertEqual(provisioned.json()["provisioning"]["overall_state"], "degraded")

        repeat = self.client.post("/api/edge/cloudflare/provision", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(repeat.json()["provisioning"]["tunnel_id"], first_tunnel_id)

        cloudflare_status = self.client.get("/api/edge/cloudflare")
        self.assertEqual(cloudflare_status.status_code, 200, cloudflare_status.text)
        self.assertEqual(cloudflare_status.json()["provisioning"]["tunnel_id"], first_tunnel_id)

        reconciled = self.client.post("/api/edge/reconcile", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(reconciled.status_code, 200, reconciled.text)
        status = self.client.get("/api/edge/status")
        self.assertEqual(status.status_code, 200, status.text)
        payload = status.json()
        self.assertTrue(payload["tunnel"]["configured"])
        self.assertEqual(payload["provisioning"]["overall_state"], "degraded")
        self.assertTrue(payload["cloudflare"]["api_token_configured"])
        self.assertEqual(payload["cloudflare"]["account_id"], "acct-env")
        self.assertEqual(payload["cloudflare"]["zone_id"], "zone-env")
        self.assertEqual(payload["cloudflare"]["tunnel_id"], first_tunnel_id)
        self.assertTrue(payload["cloudflare"]["public_dns_record_id"])
        self.assertTrue(payload["cloudflare"]["ui_dns_record_id"])
        self.assertTrue(payload["cloudflare"]["api_dns_record_id"])
        self.assertEqual(payload["cloudflare"]["public_dns_record_id"], payload["cloudflare"]["api_dns_record_id"])
        self.assertEqual(payload["tunnel"]["runtime_state"], "configured")
        self.assertFalse(payload["tunnel"]["healthy"])
        self.assertIn("last_reconcile_at", payload["reconcile_state"])

    def test_settings_context_change_clears_stale_cloudflare_metadata(self) -> None:
        settings_res = self.client.put(
            "/api/edge/cloudflare/settings",
            headers={"X-Admin-Token": "test-token"},
            json={
                "enabled": True,
                "managed_domain_base": "hexe-ai.com",
                "hostname_publication_mode": "core_id_managed",
            },
        )
        self.assertEqual(settings_res.status_code, 200, settings_res.text)
        provisioned = self.client.post("/api/edge/cloudflare/provision", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(provisioned.status_code, 200, provisioned.text)

        with patch.dict(os.environ, {"CLOUDFLARE_ZONE_ID": "zone-changed"}, clear=False):
            updated = self.client.put(
                "/api/edge/cloudflare/settings",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "enabled": True,
                    "managed_domain_base": "hexe-ai.com",
                    "hostname_publication_mode": "core_id_managed",
                },
            )
        self.assertEqual(updated.status_code, 200, updated.text)
        payload = updated.json()
        self.assertIsNone(payload["tunnel_id"])
        self.assertIsNone(payload["public_dns_record_id"])
        self.assertIsNone(payload["ui_dns_record_id"])
        self.assertEqual(payload["provisioning_state"], "not_configured")

    def test_rejects_operator_publication_on_reserved_core_paths(self) -> None:
        identity = self.client.get("/api/edge/public-identity").json()
        created = self.client.post(
            "/api/edge/publications",
            headers={"X-Admin-Token": "test-token"},
            json={
                "hostname": identity["public_hostname"],
                "path_prefix": "/api/frigate",
                "enabled": True,
                "source": "operator_defined",
                "target": {
                    "target_type": "frigate",
                    "target_id": "frigate",
                    "upstream_base_url": "http://127.0.0.1:5000",
                    "allowed_path_prefixes": ["/api/frigate"],
                },
            },
        )
        self.assertEqual(created.status_code, 400, created.text)
        self.assertEqual(created.json()["detail"], "edge_publication_reserved_core_path")

    def test_disabled_settings_ignore_custom_api_token_ref(self) -> None:
        response = self.client.put(
            "/api/edge/cloudflare/settings",
            headers={"X-Admin-Token": "test-token"},
            json={
                "enabled": False,
                "api_token_ref": "bad-ref",
                "managed_domain_base": "hexe-ai.com",
                "hostname_publication_mode": "core_id_managed",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["api_token_ref"])

    def test_enabled_settings_require_env_account_and_zone(self) -> None:
        with patch.dict(os.environ, {"CLOUDFLARE_ACCOUNT_ID": "", "CLOUDFLARE_ZONE_ID": ""}, clear=False):
            response = self.client.put(
                "/api/edge/cloudflare/settings",
                headers={"X-Admin-Token": "test-token"},
                json={
                    "enabled": True,
                    "managed_domain_base": "hexe-ai.com",
                    "hostname_publication_mode": "core_id_managed",
                },
            )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "cloudflare_settings_incomplete")

    def test_create_frigate_publication_normalizes_upstream_base_url(self) -> None:
        identity = self.client.get("/api/edge/public-identity").json()
        created = self.client.post(
            "/api/edge/publications",
            headers={"X-Admin-Token": "test-token"},
            json={
                "hostname": f"frigate.{identity['core_id']}.hexe-ai.com",
                "path_prefix": "/",
                "enabled": True,
                "source": "operator_defined",
                "target": {
                    "target_type": "frigate",
                    "target_id": "frigate",
                    "upstream_base_url": "http://localhost:5000/",
                    "allowed_path_prefixes": ["/"],
                },
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        payload = created.json()["publication"]
        self.assertEqual(payload["target"]["target_type"], "frigate")
        self.assertEqual(payload["target"]["upstream_base_url"], "http://localhost:5000")

        dry_run = self.client.post("/api/edge/cloudflare/test", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(dry_run.status_code, 200, dry_run.text)
        frigate_rules = [
            item for item in dry_run.json()["rendered_config"]["ingress"]
            if item.get("hostname") == f"frigate.{identity['core_id']}.hexe-ai.com"
        ]
        self.assertEqual(len(frigate_rules), 1)
        self.assertEqual(frigate_rules[0]["service"], "http://localhost:5000")

    def test_rejects_upstream_base_url_with_non_root_path(self) -> None:
        identity = self.client.get("/api/edge/public-identity").json()
        created = self.client.post(
            "/api/edge/publications",
            headers={"X-Admin-Token": "test-token"},
            json={
                "hostname": f"frigate.{identity['core_id']}.hexe-ai.com",
                "path_prefix": "/",
                "enabled": True,
                "source": "operator_defined",
                "target": {
                    "target_type": "frigate",
                    "target_id": "frigate",
                    "upstream_base_url": "http://localhost:5000/api",
                    "allowed_path_prefixes": ["/"],
                },
            },
        )
        self.assertEqual(created.status_code, 400, created.text)
        self.assertEqual(created.json()["detail"], "edge_target_upstream_path_not_allowed")

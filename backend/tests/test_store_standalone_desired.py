import json
import tempfile
import unittest
from pathlib import Path

from app.store.standalone_desired import (
    SSAPDesiredValidationError,
    build_desired_state,
    validate_desired_state,
    write_desired_state_atomic,
)


class TestStoreStandaloneDesired(unittest.TestCase):
    def test_build_desired_state_contains_required_ssap_fields(self) -> None:
        payload = build_desired_state(
            addon_id="mqtt",
            catalog_id="official",
            channel="stable",
            pinned_version=None,
            artifact_url="https://example.test/mqtt-0.1.2.tgz",
            sha256="a" * 64,
            publisher_key_id="publisher.dan#2026-02",
            signature_value="base64-signature",
            runtime_project_name="synthia-addon-mqtt",
            runtime_network="synthia_net",
            runtime_ports=[{"host": 9002, "container": 9002, "proto": "tcp", "purpose": "http_api"}],
            config_env={"CORE_URL": "http://127.0.0.1:9001"},
        )

        self.assertEqual(payload["ssap_version"], "1.0")
        self.assertEqual(payload["mode"], "standalone_service")
        self.assertEqual(payload["desired_state"], "running")
        self.assertEqual(payload["install_source"]["type"], "catalog")
        self.assertEqual(payload["install_source"]["catalog_id"], "official")
        self.assertEqual(payload["install_source"]["release"]["signature"]["type"], "none")
        self.assertEqual(payload["runtime"]["project_name"], "synthia-addon-mqtt")
        self.assertEqual(payload["runtime"]["network"], "synthia_net")
        self.assertEqual(payload["config"]["env"]["CORE_URL"], "http://127.0.0.1:9001")

    def test_write_desired_state_atomic_writes_json_file(self) -> None:
        payload = build_desired_state(
            addon_id="mqtt",
            catalog_id="official",
            channel="stable",
            pinned_version="0.1.2",
            artifact_url="https://example.test/mqtt-0.1.2.tgz",
            sha256="b" * 64,
            publisher_key_id="publisher.dan#2026-02",
            signature_value="base64-signature",
            runtime_project_name="synthia-addon-mqtt",
            runtime_network="synthia_net",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            desired_path = Path(tmpdir) / "services" / "mqtt" / "desired.json"
            write_desired_state_atomic(desired_path, payload)

            self.assertTrue(desired_path.exists())
            loaded = json.loads(desired_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["addon_id"], "mqtt")
            self.assertEqual(loaded["pinned_version"], "0.1.2")
            self.assertEqual(loaded["install_source"]["release"]["sha256"], "b" * 64)
            self.assertFalse(desired_path.with_suffix(".json.tmp").exists())

    def test_validate_desired_state_rejects_invalid_values(self) -> None:
        payload = build_desired_state(
            addon_id="mqtt",
            catalog_id="official",
            channel="stable",
            pinned_version="0.1.2",
            artifact_url="https://example.test/mqtt-0.1.2.tgz",
            sha256="c" * 64,
            publisher_key_id="publisher.dan#2026-02",
            signature_value="base64-signature",
            runtime_project_name="synthia-addon-mqtt",
            runtime_network="synthia_net",
        )
        payload["desired_state"] = "invalid-state"
        with self.assertRaises(SSAPDesiredValidationError) as ctx:
            validate_desired_state(payload)
        self.assertIn("ssap_desired_invalid", str(ctx.exception))

    def test_validate_desired_state_rejects_non_lowercase_sha256(self) -> None:
        payload = build_desired_state(
            addon_id="mqtt",
            catalog_id="official",
            channel="stable",
            pinned_version="0.1.2",
            artifact_url="https://example.test/mqtt-0.1.2.tgz",
            sha256="d" * 64,
            publisher_key_id="publisher.dan#2026-02",
            signature_value="base64-signature",
            runtime_project_name="synthia-addon-mqtt",
            runtime_network="synthia_net",
        )
        payload["install_source"]["release"]["sha256"] = "A" * 64
        with self.assertRaises(SSAPDesiredValidationError):
            validate_desired_state(payload)


if __name__ == "__main__":
    unittest.main()

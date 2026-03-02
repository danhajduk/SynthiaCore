from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synthia_supervisor.main import reconcile_one


def _write_desired(addon_dir: Path) -> None:
    desired = {
        "ssap_version": "1.0",
        "addon_id": "mqtt",
        "desired_state": "running",
        "pinned_version": "0.1.2",
        "install_source": {
            "type": "catalog",
            "release": {
                "artifact_url": "https://example.test/mqtt-0.1.2.tgz",
                "sha256": "a" * 64,
                "publisher_key_id": "publisher.dan#2026-02",
                "signature": {"type": "ed25519", "value": "c2ln"},
            },
        },
        "runtime": {
            "project_name": "synthia-addon-mqtt",
        },
    }
    (addon_dir / "desired.json").write_text(json.dumps(desired), encoding="utf-8")


class TestSynthiaSupervisorReconcile(unittest.TestCase):
    def test_reconcile_order_verify_then_extract_then_compose_then_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            addon_dir = Path(tmp) / "services" / "mqtt"
            version_dir = addon_dir / "versions" / "0.1.2"
            version_dir.mkdir(parents=True, exist_ok=True)
            (version_dir / "addon.tgz").write_bytes(b"artifact-bytes")
            _write_desired(addon_dir)
            calls: list[str] = []

            with patch("synthia_supervisor.main.verify_release_option_a", side_effect=lambda *a, **k: calls.append("verify")), \
                patch("synthia_supervisor.main.ensure_extracted", side_effect=lambda *a, **k: calls.append("extract")), \
                patch("synthia_supervisor.main.ensure_compose_files", side_effect=lambda *a, **k: calls.append("compose_files")), \
                patch("synthia_supervisor.main.compose_up", side_effect=lambda *a, **k: calls.append("compose_up")):
                reconcile_one(addon_dir)

            self.assertEqual(calls, ["verify", "extract", "compose_files", "compose_up"])
            self.assertTrue((addon_dir / "current").is_symlink())
            self.assertEqual((addon_dir / "current").resolve(), version_dir.resolve())
            runtime = json.loads((addon_dir / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["state"], "running")
            self.assertEqual(runtime["active_version"], "0.1.2")
            self.assertFalse(runtime["rollback_available"])
            self.assertIsNone(runtime["last_error"])

    def test_reconcile_stops_when_verify_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            addon_dir = Path(tmp) / "services" / "mqtt"
            version_dir = addon_dir / "versions" / "0.1.2"
            version_dir.mkdir(parents=True, exist_ok=True)
            (version_dir / "addon.tgz").write_bytes(b"artifact-bytes")
            _write_desired(addon_dir)

            with patch("synthia_supervisor.main.verify_release_option_a", side_effect=RuntimeError("bad-signature")), \
                patch("synthia_supervisor.main.ensure_extracted") as extract_mock, \
                patch("synthia_supervisor.main.ensure_compose_files") as compose_files_mock, \
                patch("synthia_supervisor.main.compose_up") as compose_up_mock:
                reconcile_one(addon_dir)

            extract_mock.assert_not_called()
            compose_files_mock.assert_not_called()
            compose_up_mock.assert_not_called()
            runtime = json.loads((addon_dir / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["state"], "error")
            self.assertIn("bad-signature", runtime.get("error", ""))
            self.assertFalse(runtime["rollback_available"])
            self.assertIsNone(runtime["previous_version"])
            self.assertIn("bad-signature", runtime.get("last_error", ""))

    def test_reconcile_does_not_activate_new_current_when_compose_up_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            addon_dir = Path(tmp) / "services" / "mqtt"
            old_version_dir = addon_dir / "versions" / "0.1.1"
            new_version_dir = addon_dir / "versions" / "0.1.2"
            old_version_dir.mkdir(parents=True, exist_ok=True)
            new_version_dir.mkdir(parents=True, exist_ok=True)
            (new_version_dir / "addon.tgz").write_bytes(b"artifact-bytes")
            current = addon_dir / "current"
            current.symlink_to(old_version_dir)
            _write_desired(addon_dir)

            with patch("synthia_supervisor.main.verify_release_option_a"), \
                patch("synthia_supervisor.main.ensure_extracted"), \
                patch("synthia_supervisor.main.ensure_compose_files"), \
                patch("synthia_supervisor.main.compose_up", side_effect=RuntimeError("compose-failed")):
                reconcile_one(addon_dir)

            self.assertTrue(current.is_symlink())
            self.assertEqual(current.resolve(), old_version_dir.resolve())
            runtime = json.loads((addon_dir / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["state"], "error")
            self.assertIn("compose-failed", runtime.get("error", ""))
            self.assertEqual(runtime.get("previous_version"), "0.1.1")
            self.assertTrue(runtime["rollback_available"])
            self.assertIn("compose-failed", runtime.get("last_error", ""))


if __name__ == "__main__":
    unittest.main()

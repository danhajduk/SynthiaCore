from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import os
from unittest.mock import patch

from synthia_supervisor.main import reconcile_one


def _write_desired(addon_dir: Path, version: str = "0.1.2") -> None:
    desired = {
        "ssap_version": "1.0",
        "addon_id": "mqtt",
        "desired_state": "running",
        "pinned_version": version,
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
    def test_reconcile_order_extract_then_compose_then_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            addon_dir = Path(tmp) / "services" / "mqtt"
            version_dir = addon_dir / "versions" / "0.1.2"
            version_dir.mkdir(parents=True, exist_ok=True)
            (version_dir / "addon.tgz").write_bytes(b"artifact-bytes")
            _write_desired(addon_dir)
            calls: list[str] = []

            with patch("synthia_supervisor.main.ensure_extracted", side_effect=lambda *a, **k: calls.append("extract")), \
                patch("synthia_supervisor.main.ensure_compose_files", side_effect=lambda *a, **k: calls.append("compose_files")), \
                patch("synthia_supervisor.main.compose_up", side_effect=lambda *a, **k: calls.append("compose_up")):
                reconcile_one(addon_dir)

            self.assertEqual(calls, ["extract", "compose_files", "compose_up"])
            self.assertTrue((addon_dir / "current").is_symlink())
            self.assertEqual((addon_dir / "current").resolve(), version_dir.resolve())
            runtime = json.loads((addon_dir / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["state"], "running")
            self.assertEqual(runtime["active_version"], "0.1.2")
            self.assertFalse(runtime["rollback_available"])
            self.assertIsNone(runtime["last_error"])

    def test_reconcile_stops_when_extract_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            addon_dir = Path(tmp) / "services" / "mqtt"
            version_dir = addon_dir / "versions" / "0.1.2"
            version_dir.mkdir(parents=True, exist_ok=True)
            (version_dir / "addon.tgz").write_bytes(b"artifact-bytes")
            _write_desired(addon_dir)

            with patch("synthia_supervisor.main.ensure_extracted", side_effect=RuntimeError("extract-failed")) as extract_mock, \
                patch("synthia_supervisor.main.ensure_compose_files") as compose_files_mock, \
                patch("synthia_supervisor.main.compose_up") as compose_up_mock:
                reconcile_one(addon_dir)

            extract_mock.assert_called_once()
            compose_files_mock.assert_not_called()
            compose_up_mock.assert_not_called()
            runtime = json.loads((addon_dir / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["state"], "error")
            self.assertIn("extract-failed", runtime.get("error", ""))
            self.assertFalse(runtime["rollback_available"])
            self.assertIsNone(runtime["previous_version"])
            self.assertIn("extract-failed", runtime.get("last_error", ""))

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

            with patch("synthia_supervisor.main.ensure_extracted"), \
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

    def test_reconcile_upgrade_success_switches_current_and_records_previous_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            addon_dir = Path(tmp) / "services" / "mqtt"
            old_version_dir = addon_dir / "versions" / "0.1.1"
            new_version_dir = addon_dir / "versions" / "0.1.2"
            old_version_dir.mkdir(parents=True, exist_ok=True)
            new_version_dir.mkdir(parents=True, exist_ok=True)
            (new_version_dir / "addon.tgz").write_bytes(b"artifact-bytes")
            (addon_dir / "current").symlink_to(old_version_dir)
            _write_desired(addon_dir)

            with patch("synthia_supervisor.main.ensure_extracted"), \
                patch("synthia_supervisor.main.ensure_compose_files"), \
                patch("synthia_supervisor.main.compose_up"):
                reconcile_one(addon_dir)

            current = addon_dir / "current"
            self.assertTrue(current.is_symlink())
            self.assertEqual(current.resolve(), new_version_dir.resolve())
            runtime = json.loads((addon_dir / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["state"], "running")
            self.assertEqual(runtime["active_version"], "0.1.2")
            self.assertEqual(runtime["previous_version"], "0.1.1")
            self.assertTrue(runtime["rollback_available"])

    def test_reconcile_prunes_old_versions_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            addon_dir = Path(tmp) / "services" / "mqtt"
            versions = []
            for version in ("0.1.1", "0.1.2", "0.1.3", "0.1.4"):
                version_dir = addon_dir / "versions" / version
                version_dir.mkdir(parents=True, exist_ok=True)
                (version_dir / "addon.tgz").write_bytes(b"artifact-bytes")
                versions.append(version_dir)
            for idx, version_dir in enumerate(versions, start=1):
                ts = 1700000000 + idx
                os.utime(version_dir, (ts, ts))
            (addon_dir / "current").symlink_to(addon_dir / "versions" / "0.1.3")
            _write_desired(addon_dir, version="0.1.4")

            with patch.dict("os.environ", {"SYNTHIA_SUPERVISOR_KEEP_VERSIONS": "3"}, clear=False), \
                patch("synthia_supervisor.main.ensure_extracted"), \
                patch("synthia_supervisor.main.ensure_compose_files"), \
                patch("synthia_supervisor.main.compose_up"):
                reconcile_one(addon_dir)

            remaining = sorted(
                p.name for p in (addon_dir / "versions").iterdir() if p.is_dir()
            )
            self.assertEqual(remaining, ["0.1.2", "0.1.3", "0.1.4"])

    def test_reconcile_does_not_prune_versions_when_reconcile_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            addon_dir = Path(tmp) / "services" / "mqtt"
            for version in ("0.1.1", "0.1.2", "0.1.3", "0.1.4"):
                version_dir = addon_dir / "versions" / version
                version_dir.mkdir(parents=True, exist_ok=True)
                (version_dir / "addon.tgz").write_bytes(b"artifact-bytes")
            _write_desired(addon_dir, version="0.1.4")

            with patch.dict("os.environ", {"SYNTHIA_SUPERVISOR_KEEP_VERSIONS": "3"}, clear=False), \
                patch("synthia_supervisor.main.ensure_extracted"), \
                patch("synthia_supervisor.main.ensure_compose_files"), \
                patch("synthia_supervisor.main.compose_up", side_effect=RuntimeError("compose-failed")):
                reconcile_one(addon_dir)

            remaining = sorted(
                p.name for p in (addon_dir / "versions").iterdir() if p.is_dir()
            )
            self.assertEqual(remaining, ["0.1.1", "0.1.2", "0.1.3", "0.1.4"])


if __name__ == "__main__":
    unittest.main()

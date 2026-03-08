from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import os
from unittest.mock import patch

from synthia_supervisor.main import reconcile_one, run_post_reconcile_hooks


def _write_desired(addon_dir: Path, version: str = "0.1.2", revision: str = "rev-1", ports: list[dict] | None = None) -> None:
    desired = {
        "ssap_version": "1.0",
        "addon_id": "mqtt",
        "desired_state": "running",
        "desired_revision": revision,
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
            "network": "synthia_net",
            "ports": list(ports or []),
            "bind_localhost": True,
        },
    }
    (addon_dir / "desired.json").write_text(json.dumps(desired), encoding="utf-8")


class TestSynthiaSupervisorReconcile(unittest.TestCase):
    def test_reconcile_returns_none_when_desired_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            addon_dir = Path(tmp) / "services" / "mqtt"
            addon_dir.mkdir(parents=True, exist_ok=True)
            result = reconcile_one(addon_dir)
            self.assertIsNone(result)

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
                result = reconcile_one(addon_dir)
            self.assertIsNotNone(result)
            hooks = run_post_reconcile_hooks(addon_dir, result)  # type: ignore[arg-type]
            self.assertIsInstance(hooks.get("cleanup"), dict)

            self.assertEqual(calls, ["extract", "compose_files", "compose_up"])
            self.assertTrue((addon_dir / "current").is_symlink())
            self.assertEqual((addon_dir / "current").resolve(), version_dir.resolve())
            runtime = json.loads((addon_dir / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["state"], "running")
            self.assertEqual(runtime["active_version"], "0.1.2")
            self.assertFalse(runtime["rollback_available"])
            self.assertIsNone(runtime["last_error"])
            self.assertEqual(runtime["last_applied_desired_revision"], "rev-1")
            self.assertTrue(str(runtime.get("last_applied_compose_digest", "")).strip())
            self.assertEqual(result.final_state, "running")  # type: ignore[union-attr]
            self.assertEqual(result.desired_state, "running")  # type: ignore[union-attr]

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
                result = reconcile_one(addon_dir)
            self.assertIsNotNone(result)
            hooks = run_post_reconcile_hooks(addon_dir, result)  # type: ignore[arg-type]
            self.assertIsNone(hooks.get("cleanup"))

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
                result = reconcile_one(addon_dir)
            self.assertIsNotNone(result)
            hooks = run_post_reconcile_hooks(addon_dir, result)  # type: ignore[arg-type]
            self.assertIsNone(hooks.get("cleanup"))

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
                result = reconcile_one(addon_dir)
            self.assertIsNotNone(result)
            hooks = run_post_reconcile_hooks(addon_dir, result)  # type: ignore[arg-type]
            self.assertIsInstance(hooks.get("cleanup"), dict)

            current = addon_dir / "current"
            self.assertTrue(current.is_symlink())
            self.assertEqual(current.resolve(), new_version_dir.resolve())
            runtime = json.loads((addon_dir / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["state"], "running")
            self.assertEqual(runtime["active_version"], "0.1.2")
            self.assertEqual(runtime["previous_version"], "0.1.1")
            self.assertTrue(runtime["rollback_available"])

    def test_reconcile_noop_when_desired_revision_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            addon_dir = Path(tmp) / "services" / "mqtt"
            version_dir = addon_dir / "versions" / "0.1.2"
            version_dir.mkdir(parents=True, exist_ok=True)
            (version_dir / "addon.tgz").write_bytes(b"artifact-bytes")
            runtime_path = addon_dir / "runtime.json"
            runtime_path.write_text(
                json.dumps(
                    {
                        "ssap_version": "1.0",
                        "addon_id": "mqtt",
                        "active_version": "0.1.2",
                        "state": "running",
                        "last_applied_desired_revision": "rev-1",
                        "last_applied_compose_digest": "abc",
                    }
                ),
                encoding="utf-8",
            )
            _write_desired(addon_dir, revision="rev-1")
            with patch("synthia_supervisor.main.ensure_extracted") as extract_mock, \
                patch("synthia_supervisor.main.ensure_compose_files") as compose_mock, \
                patch("synthia_supervisor.main.compose_up") as up_mock:
                result = reconcile_one(addon_dir)
            self.assertIsNotNone(result)
            extract_mock.assert_not_called()
            compose_mock.assert_not_called()
            up_mock.assert_not_called()
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            self.assertEqual(runtime["last_applied_desired_revision"], "rev-1")

    def test_reconcile_regenerates_compose_when_same_version_compose_inputs_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            addon_dir = Path(tmp) / "services" / "mqtt"
            version_dir = addon_dir / "versions" / "0.1.2"
            extracted_dir = version_dir / "extracted"
            extracted_dir.mkdir(parents=True, exist_ok=True)
            (version_dir / "addon.tgz").write_bytes(b"artifact-bytes")
            compose_file = version_dir / "docker-compose.yml"
            compose_file.write_text("services:\n  mqtt:\n    image: old\n", encoding="utf-8")
            runtime_path = addon_dir / "runtime.json"
            runtime_path.write_text(
                json.dumps(
                    {
                        "ssap_version": "1.0",
                        "addon_id": "mqtt",
                        "active_version": "0.1.2",
                        "state": "running",
                        "last_applied_desired_revision": "rev-1",
                        "last_applied_compose_digest": "old-digest",
                    }
                ),
                encoding="utf-8",
            )
            _write_desired(addon_dir, revision="rev-2", ports=[{"host": 18080, "container": 8080, "proto": "tcp"}])

            with patch("synthia_supervisor.main.ensure_extracted"), \
                patch("synthia_supervisor.main.compose_up"):
                result = reconcile_one(addon_dir)
            self.assertIsNotNone(result)
            compose_text = compose_file.read_text(encoding="utf-8")
            self.assertIn("18080:8080/tcp", compose_text)
            self.assertNotIn("image: old", compose_text)
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            self.assertEqual(runtime["last_applied_desired_revision"], "rev-2")
            self.assertNotEqual(runtime["last_applied_compose_digest"], "old-digest")

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
                result = reconcile_one(addon_dir)
            self.assertIsNotNone(result)
            run_post_reconcile_hooks(addon_dir, result)  # type: ignore[arg-type]

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
                result = reconcile_one(addon_dir)
            self.assertIsNotNone(result)
            run_post_reconcile_hooks(addon_dir, result)  # type: ignore[arg-type]

            remaining = sorted(
                p.name for p in (addon_dir / "versions").iterdir() if p.is_dir()
            )
            self.assertEqual(remaining, ["0.1.1", "0.1.2", "0.1.3", "0.1.4"])


if __name__ == "__main__":
    unittest.main()

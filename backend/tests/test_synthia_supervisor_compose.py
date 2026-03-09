from __future__ import annotations

import os
import subprocess
import tarfile
import tempfile
import time
import unittest
import hashlib
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from synthia_supervisor.docker_compose import compose_up, ensure_compose_files, ensure_extracted
from synthia_supervisor.models import DesiredState


class TestSynthiaSupervisorCompose(unittest.TestCase):
    def test_ensure_extracted_creates_runtime_dir_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(tmp) / "extracted"
            extracted.mkdir(parents=True, exist_ok=True)
            self.assertFalse((extracted / "runtime").exists())
            ensure_extracted(Path(tmp) / "artifact.tgz", extracted)
            self.assertTrue((extracted / "runtime").is_dir())

    def test_ensure_extracted_creates_runtime_dir_after_extract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(tmp) / "extracted"
            artifact = Path(tmp) / "artifact.tgz"
            artifact.write_text("", encoding="utf-8")
            with patch("synthia_supervisor.docker_compose.subprocess.run") as run_mock:
                ensure_extracted(artifact, extracted)
                run_mock.assert_called_once()
            self.assertTrue((extracted / "runtime").is_dir())

    def test_ensure_extracted_normalizes_file_mtime_after_tar_extract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(tmp) / "extracted"
            artifact = Path(tmp) / "artifact.tgz"
            old_epoch = 946684800  # 2000-01-01 UTC
            with tarfile.open(artifact, "w:gz") as tf:
                payload = b'{"version":"0.2.6"}\n'
                info = tarfile.TarInfo(name="manifest.json")
                info.size = len(payload)
                info.mtime = old_epoch
                tf.addfile(info, fileobj=BytesIO(payload))

            start = time.time()
            ensure_extracted(artifact, extracted)

            manifest_path = extracted / "manifest.json"
            self.assertTrue(manifest_path.exists())
            self.assertGreaterEqual(manifest_path.stat().st_mtime, start - 1.0)

    def test_ensure_extracted_reextracts_when_artifact_hash_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(tmp) / "extracted"
            extracted.mkdir(parents=True, exist_ok=True)
            (extracted / "stale.txt").write_text("old", encoding="utf-8")
            (extracted / ".artifact.sha256").write_text("oldhash\n", encoding="utf-8")
            artifact = Path(tmp) / "artifact.tgz"
            with tarfile.open(artifact, "w:gz") as tf:
                payload = b'{"id":"mqtt","version":"0.2.6"}\n'
                info = tarfile.TarInfo(name="manifest.json")
                info.size = len(payload)
                tf.addfile(info, fileobj=BytesIO(payload))

            ensure_extracted(artifact, extracted)

            self.assertTrue((extracted / "manifest.json").exists())
            self.assertFalse((extracted / "stale.txt").exists())
            expected_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
            self.assertEqual((extracted / ".artifact.sha256").read_text(encoding="utf-8").strip(), expected_hash)

    def test_ensure_extracted_skips_reextract_when_artifact_hash_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(tmp) / "extracted"
            extracted.mkdir(parents=True, exist_ok=True)
            artifact = Path(tmp) / "artifact.tgz"
            with tarfile.open(artifact, "w:gz") as tf:
                payload = b'{"id":"mqtt","version":"0.2.6"}\n'
                info = tarfile.TarInfo(name="manifest.json")
                info.size = len(payload)
                tf.addfile(info, fileobj=BytesIO(payload))
            artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
            (extracted / ".artifact.sha256").write_text(f"{artifact_hash}\n", encoding="utf-8")

            with patch("synthia_supervisor.docker_compose.subprocess.run") as run_mock:
                ensure_extracted(artifact, extracted)
                run_mock.assert_not_called()
            self.assertTrue((extracted / "runtime").is_dir())

    def test_compose_defaults_include_security_guardrails(self) -> None:
        desired = DesiredState.model_validate(
            {
                "ssap_version": "1.0",
                "addon_id": "mqtt",
                "desired_state": "running",
                "install_source": {
                    "type": "catalog",
                    "release": {
                        "artifact_url": "https://example.test/mqtt.tgz",
                        "sha256": "a" * 64,
                        "publisher_key_id": "publisher.dan#2026-02",
                        "signature": {"type": "ed25519", "value": "sig"},
                    },
                },
                "runtime": {
                    "project_name": "synthia-addon-mqtt",
                    "network": "synthia_net",
                    "ports": [{"host": 9002, "container": 9002, "proto": "tcp"}],
                },
                "config": {"env": {"CORE_URL": "http://127.0.0.1:9001"}},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(tmp) / "extracted"
            extracted.mkdir(parents=True, exist_ok=True)
            compose_file = Path(tmp) / "docker-compose.yml"
            env_file = Path(tmp) / "runtime.env"
            desired_file = Path(tmp) / "desired.json"
            runtime_file = Path(tmp) / "runtime.json"
            desired_file.write_text("{}\n", encoding="utf-8")
            runtime_file.write_text("{}\n", encoding="utf-8")
            with patch.dict(os.environ, {"SYNTHIA_SERVICE_TOKEN": "token-123"}, clear=False):
                ensure_compose_files(
                    desired,
                    extracted,
                    compose_file,
                    env_file,
                    desired_file,
                    runtime_file,
                    "mqtt",
                )

            compose_text = compose_file.read_text(encoding="utf-8")
            env_text = env_file.read_text(encoding="utf-8")
            self.assertIn("privileged: false", compose_text)
            self.assertIn("no-new-privileges:true", compose_text)
            self.assertNotIn("network_mode: host", compose_text)
            self.assertIn("networks:", compose_text)
            self.assertIn("synthia_net", compose_text)
            self.assertIn("127.0.0.1:9002:9002/tcp", compose_text)
            self.assertIn(f"{desired_file}:/state/desired.json", compose_text)
            self.assertIn(f"{runtime_file}:/state/runtime.json", compose_text)
            self.assertIn(f"{compose_file}:/state/docker-compose.yml:ro", compose_text)
            self.assertIn("CORE_URL=http://127.0.0.1:9001", env_text)
            self.assertIn("SYNTHIA_SERVICE_TOKEN=token-123", env_text)

    def test_compose_uses_host_publish_when_bind_localhost_disabled(self) -> None:
        desired = DesiredState.model_validate(
            {
                "ssap_version": "1.0",
                "addon_id": "mqtt",
                "desired_state": "running",
                "install_source": {
                    "type": "catalog",
                    "release": {
                        "artifact_url": "https://example.test/mqtt.tgz",
                        "sha256": "a" * 64,
                    },
                },
                "runtime": {
                    "project_name": "synthia-addon-mqtt",
                    "network": "synthia_net",
                    "bind_localhost": False,
                    "ports": [{"host": 18081, "container": 18081, "proto": "tcp"}],
                },
                "config": {"env": {}},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(tmp) / "extracted"
            extracted.mkdir(parents=True, exist_ok=True)
            compose_file = Path(tmp) / "docker-compose.yml"
            env_file = Path(tmp) / "runtime.env"
            desired_file = Path(tmp) / "desired.json"
            runtime_file = Path(tmp) / "runtime.json"
            desired_file.write_text("{}\n", encoding="utf-8")
            runtime_file.write_text("{}\n", encoding="utf-8")
            ensure_compose_files(desired, extracted, compose_file, env_file, desired_file, runtime_file, "mqtt")

            compose_text = compose_file.read_text(encoding="utf-8")
            self.assertIn("0.0.0.0:18081:18081/tcp", compose_text)

    def test_compose_includes_cpu_and_memory_limits_when_specified(self) -> None:
        desired = DesiredState.model_validate(
            {
                "ssap_version": "1.0",
                "addon_id": "mqtt",
                "desired_state": "running",
                "install_source": {
                    "type": "catalog",
                    "release": {
                        "artifact_url": "https://example.test/mqtt.tgz",
                        "sha256": "a" * 64,
                    },
                },
                "runtime": {
                    "project_name": "synthia-addon-mqtt",
                    "network": "synthia_net",
                    "cpu": 1.25,
                    "memory": "768m",
                },
                "config": {"env": {}},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(tmp) / "extracted"
            extracted.mkdir(parents=True, exist_ok=True)
            compose_file = Path(tmp) / "docker-compose.yml"
            env_file = Path(tmp) / "runtime.env"
            desired_file = Path(tmp) / "desired.json"
            runtime_file = Path(tmp) / "runtime.json"
            desired_file.write_text("{}\n", encoding="utf-8")
            runtime_file.write_text("{}\n", encoding="utf-8")
            ensure_compose_files(desired, extracted, compose_file, env_file, desired_file, runtime_file, "mqtt")

            compose_text = compose_file.read_text(encoding="utf-8")
            self.assertIn("cpus: 1.25", compose_text)
            self.assertIn("mem_limit: 768m", compose_text)

    def test_compose_regenerates_existing_file_when_state_mounts_are_read_only(self) -> None:
        desired = DesiredState.model_validate(
            {
                "ssap_version": "1.0",
                "addon_id": "mqtt",
                "desired_state": "running",
                "install_source": {
                    "type": "catalog",
                    "release": {
                        "artifact_url": "https://example.test/mqtt.tgz",
                        "sha256": "a" * 64,
                    },
                },
                "runtime": {
                    "project_name": "synthia-addon-mqtt",
                    "network": "synthia_net",
                },
                "config": {"env": {}},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(tmp) / "extracted"
            extracted.mkdir(parents=True, exist_ok=True)
            compose_file = Path(tmp) / "docker-compose.yml"
            env_file = Path(tmp) / "runtime.env"
            desired_file = Path(tmp) / "desired.json"
            runtime_file = Path(tmp) / "runtime.json"
            desired_file.write_text("{}\n", encoding="utf-8")
            runtime_file.write_text("{}\n", encoding="utf-8")
            compose_file.write_text(
                f"services:\n  mqtt:\n    volumes:\n      - {desired_file}:/state/desired.json:ro\n      - {runtime_file}:/state/runtime.json:ro\n",
                encoding="utf-8",
            )

            ensure_compose_files(desired, extracted, compose_file, env_file, desired_file, runtime_file, "mqtt")

            compose_text = compose_file.read_text(encoding="utf-8")
            self.assertNotIn("/state/desired.json:ro", compose_text)
            self.assertNotIn("/state/runtime.json:ro", compose_text)
            self.assertIn(f"{desired_file}:/state/desired.json", compose_text)
            self.assertIn(f"{runtime_file}:/state/runtime.json", compose_text)

    def test_compose_up_reports_stderr_summary_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            compose_file = Path(tmp) / "docker-compose.yml"
            compose_file.write_text("services: {}\n", encoding="utf-8")
            failed = subprocess.CompletedProcess(
                args=["docker", "compose"],
                returncode=1,
                stdout="",
                stderr="failed to solve: missing Dockerfile",
            )
            with patch("synthia_supervisor.docker_compose.subprocess.run", return_value=failed):
                with self.assertRaises(RuntimeError) as ctx:
                    compose_up(compose_file, "synthia-addon-mqtt")
            self.assertIn("compose_up_failed", str(ctx.exception))
            self.assertIn("missing Dockerfile", str(ctx.exception))

    def test_compose_up_runs_no_cache_build_then_force_recreate_when_force_rebuild_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            compose_file = Path(tmp) / "docker-compose.yml"
            compose_file.write_text("services: {}\n", encoding="utf-8")
            ok = subprocess.CompletedProcess(
                args=["docker", "compose"],
                returncode=0,
                stdout="ok",
                stderr="",
            )
            with patch("synthia_supervisor.docker_compose.subprocess.run", return_value=ok) as run_mock:
                compose_up(compose_file, "synthia-addon-mqtt", force_rebuild=True)
            self.assertEqual(run_mock.call_count, 2)
            build_args = run_mock.call_args_list[0].args[0]
            up_args = run_mock.call_args_list[1].args[0]
            self.assertIn("build", build_args)
            self.assertIn("--no-cache", build_args)
            self.assertNotIn("--build", up_args)
            self.assertIn("--force-recreate", up_args)

    def test_compose_up_accepts_multiple_compose_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_file = Path(tmp) / "docker-compose.yml"
            group_file = Path(tmp) / "docker-compose.group-broker.yml"
            base_file.write_text("services: {}\n", encoding="utf-8")
            group_file.write_text("services: {}\n", encoding="utf-8")
            ok = subprocess.CompletedProcess(args=["docker", "compose"], returncode=0, stdout="ok", stderr="")
            with patch("synthia_supervisor.docker_compose.subprocess.run", return_value=ok) as run_mock:
                compose_up([base_file, group_file], "synthia-addon-mqtt")
            args = run_mock.call_args.args[0]
            self.assertEqual(args[:2], ["docker", "compose"])
            self.assertIn(str(base_file), args)
            self.assertIn(str(group_file), args)
            self.assertIn("--remove-orphans", args)


if __name__ == "__main__":
    unittest.main()

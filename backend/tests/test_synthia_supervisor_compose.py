from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
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
            with patch.dict(os.environ, {"SYNTHIA_SERVICE_TOKEN": "token-123"}, clear=False):
                ensure_compose_files(desired, extracted, compose_file, env_file)

            compose_text = compose_file.read_text(encoding="utf-8")
            env_text = env_file.read_text(encoding="utf-8")
            self.assertIn("privileged: false", compose_text)
            self.assertIn("no-new-privileges:true", compose_text)
            self.assertNotIn("network_mode: host", compose_text)
            self.assertIn("networks:", compose_text)
            self.assertIn("synthia_net", compose_text)
            self.assertIn("127.0.0.1:9002:9002/tcp", compose_text)
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
            ensure_compose_files(desired, extracted, compose_file, env_file)

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
            ensure_compose_files(desired, extracted, compose_file, env_file)

            compose_text = compose_file.read_text(encoding="utf-8")
            self.assertIn("cpus: 1.25", compose_text)
            self.assertIn("mem_limit: 768m", compose_text)

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


if __name__ == "__main__":
    unittest.main()

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.system.mqtt.runtime_boundary import (
    DockerMosquittoRuntimeBoundary,
    InMemoryBrokerRuntimeBoundary,
    MosquittoProcessRuntimeBoundary,
)


class TestMqttRuntimeBoundary(unittest.TestCase):
    def test_runtime_boundary_lifecycle(self) -> None:
        boundary = InMemoryBrokerRuntimeBoundary()

        initial = asyncio.run(boundary.get_status())
        self.assertEqual(initial.state, "stopped")
        self.assertFalse(initial.healthy)

        started = asyncio.run(boundary.ensure_running())
        self.assertEqual(started.state, "running")
        self.assertTrue(started.healthy)

        reloaded = asyncio.run(boundary.reload())
        self.assertEqual(reloaded.state, "running")
        self.assertTrue(reloaded.healthy)

        restarted = asyncio.run(boundary.controlled_restart())
        self.assertEqual(restarted.state, "running")
        self.assertTrue(restarted.healthy)

        stopped = asyncio.run(boundary.stop())
        self.assertEqual(stopped.state, "stopped")
        self.assertFalse(stopped.healthy)

    def test_docker_boundary_reports_degraded_when_docker_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live_dir = Path(tmp) / "live"
            data_dir = Path(tmp) / "data"
            log_dir = Path(tmp) / "logs"
            live_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            log_dir.mkdir(parents=True, exist_ok=True)
            (live_dir / "broker.conf").write_text("listener 1883\n", encoding="utf-8")
            (live_dir / "acl_compiled.conf").write_text("topic readwrite #\n", encoding="utf-8")
            (live_dir / "passwords.conf").write_text("user:$7$hash\n", encoding="utf-8")
            boundary = DockerMosquittoRuntimeBoundary(
                live_dir=str(live_dir),
                data_dir=str(data_dir),
                log_dir=str(log_dir),
                container_name="synthia-mqtt-broker-test-missing-docker",
            )
            with patch("shutil.which", return_value=None):
                status = asyncio.run(boundary.ensure_running())
            self.assertEqual(status.state, "stopped")
            self.assertFalse(status.healthy)
            self.assertEqual(status.degraded_reason, "docker_binary_not_found")

    def test_legacy_process_class_aliases_to_docker_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live_dir = Path(tmp) / "live"
            data_dir = Path(tmp) / "data"
            log_dir = Path(tmp) / "logs"
            live_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            log_dir.mkdir(parents=True, exist_ok=True)
            (live_dir / "broker.conf").write_text("listener 1883\n", encoding="utf-8")
            (live_dir / "acl_compiled.conf").write_text("topic readwrite #\n", encoding="utf-8")
            (live_dir / "passwords.conf").write_text("user:$7$hash\n", encoding="utf-8")
            boundary = MosquittoProcessRuntimeBoundary(
                live_dir=str(live_dir),
                data_dir=str(data_dir),
                log_dir=str(log_dir),
                container_name="synthia-mqtt-broker-test-legacy-alias",
            )
            self.assertIsInstance(boundary, DockerMosquittoRuntimeBoundary)

    def test_docker_boundary_preflight_reports_missing_live_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live_dir = Path(tmp) / "live"
            data_dir = Path(tmp) / "data"
            log_dir = Path(tmp) / "logs"
            live_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            log_dir.mkdir(parents=True, exist_ok=True)
            (live_dir / "broker.conf").write_text("listener 1883\n", encoding="utf-8")
            boundary = DockerMosquittoRuntimeBoundary(
                live_dir=str(live_dir),
                data_dir=str(data_dir),
                log_dir=str(log_dir),
                container_name="synthia-mqtt-broker-test-preflight",
            )
            status = asyncio.run(boundary.ensure_running())
            self.assertEqual(status.state, "stopped")
            self.assertFalse(status.healthy)
            self.assertTrue(str(status.degraded_reason or "").startswith("config_missing:"))
            self.assertIn("expected=", str(status.degraded_reason))
            self.assertIn("staged_exists=false", str(status.degraded_reason))
            self.assertIn("live_dir_exists=true", str(status.degraded_reason))
            self.assertIn("run_setup_apply_or_runtime_rebuild", str(status.degraded_reason))

    def test_docker_boundary_start_publishes_runtime_ports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live_dir = root / "live"
            data_dir = root / "data"
            log_dir = root / "logs"
            live_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            log_dir.mkdir(parents=True, exist_ok=True)
            (live_dir / "broker.conf").write_text("listener 1883\n", encoding="utf-8")
            (live_dir / "acl_compiled.conf").write_text("topic readwrite #\n", encoding="utf-8")
            (live_dir / "passwords.conf").write_text("user:$7$hash\n", encoding="utf-8")
            boundary = DockerMosquittoRuntimeBoundary(
                live_dir=str(live_dir),
                data_dir=str(data_dir),
                log_dir=str(log_dir),
                port=1883,
                bootstrap_port=1884,
            )
            calls: list[list[str]] = []

            def _fake_cmd(args: list[str]):
                calls.append(list(args))
                cmd = " ".join(args)
                if cmd.startswith("ps -a"):
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout="", stderr="")
                if cmd.startswith("ps --"):
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout="", stderr="")
                if cmd.startswith("run "):
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout="containerid\n", stderr="")
                return subprocess.CompletedProcess(["docker", *args], 0, stdout="", stderr="")

            with patch.object(boundary, "_docker_available", return_value=True):
                with patch.object(boundary, "_docker_cmd", side_effect=_fake_cmd):
                    status = asyncio.run(boundary.ensure_running())

            self.assertFalse(status.healthy)
            run_call = next(call for call in calls if call and call[0] == "run")
            self.assertIn("-p", run_call)
            self.assertIn("1883:1883", run_call)
            self.assertIn("1884:1884", run_call)
            self.assertNotIn("--network", run_call)

    def test_docker_boundary_prepares_runtime_permissions_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live_dir = root / "live"
            data_dir = root / "data"
            log_dir = root / "logs"
            live_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            log_dir.mkdir(parents=True, exist_ok=True)
            (live_dir / "broker.conf").write_text("listener 1883\n", encoding="utf-8")
            (live_dir / "acl_compiled.conf").write_text("topic readwrite #\n", encoding="utf-8")
            (live_dir / "passwords.conf").write_text("user:$7$hash\n", encoding="utf-8")
            (live_dir / "passwords.conf").chmod(0o600)
            data_dir.chmod(0o755)
            log_dir.chmod(0o755)
            boundary = DockerMosquittoRuntimeBoundary(
                live_dir=str(live_dir),
                data_dir=str(data_dir),
                log_dir=str(log_dir),
            )

            def _fake_cmd(args: list[str]):
                cmd = " ".join(args)
                if cmd.startswith("ps -a"):
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout="", stderr="")
                if cmd.startswith("ps --"):
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout="", stderr="")
                if cmd.startswith("run "):
                    return subprocess.CompletedProcess(["docker", *args], 1, stdout="", stderr="run_failed")
                return subprocess.CompletedProcess(["docker", *args], 0, stdout="", stderr="")

            with patch.object(boundary, "_docker_available", return_value=True):
                with patch.object(boundary, "_docker_cmd", side_effect=_fake_cmd):
                    asyncio.run(boundary.ensure_running())

            self.assertEqual(data_dir.stat().st_mode & 0o777, 0o777)
            self.assertEqual(log_dir.stat().st_mode & 0o777, 0o777)
            self.assertEqual((live_dir / "passwords.conf").stat().st_mode & 0o777, 0o644)

    def test_docker_boundary_starts_existing_container_without_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live_dir = root / "live"
            data_dir = root / "data"
            log_dir = root / "logs"
            live_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            log_dir.mkdir(parents=True, exist_ok=True)
            (live_dir / "broker.conf").write_text("listener 1883\n", encoding="utf-8")
            (live_dir / "acl_compiled.conf").write_text("topic readwrite #\n", encoding="utf-8")
            (live_dir / "passwords.conf").write_text("user:$7$hash\n", encoding="utf-8")
            boundary = DockerMosquittoRuntimeBoundary(
                live_dir=str(live_dir),
                data_dir=str(data_dir),
                log_dir=str(log_dir),
                container_name="synthia-mqtt-broker-test-reuse",
            )
            calls: list[list[str]] = []
            running = {"value": False}

            def _fake_cmd(args: list[str]):
                calls.append(list(args))
                cmd = " ".join(args)
                if cmd.startswith("ps -a"):
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout="synthia-mqtt-broker-test-reuse\n", stderr="")
                if cmd.startswith("ps --"):
                    out = "synthia-mqtt-broker-test-reuse\n" if running["value"] else ""
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout=out, stderr="")
                if cmd.startswith("inspect --format"):
                    payload = '{"1883/tcp":[{"HostIp":"0.0.0.0","HostPort":"1883"}],"1884/tcp":[{"HostIp":"0.0.0.0","HostPort":"1884"}]}'
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout=payload, stderr="")
                if cmd.startswith("start "):
                    running["value"] = True
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout="started\n", stderr="")
                return subprocess.CompletedProcess(["docker", *args], 0, stdout="", stderr="")

            with patch.object(boundary, "_docker_available", return_value=True):
                with patch.object(boundary, "_can_connect", return_value=True):
                    with patch.object(boundary, "_docker_cmd", side_effect=_fake_cmd):
                        status = asyncio.run(boundary.ensure_running())

            self.assertTrue(status.healthy)
            self.assertTrue(any(call and call[0] == "start" for call in calls))
            self.assertFalse(any(call and call[0] == "run" for call in calls))

    def test_docker_boundary_recreates_container_when_port_bindings_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live_dir = root / "live"
            data_dir = root / "data"
            log_dir = root / "logs"
            live_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            log_dir.mkdir(parents=True, exist_ok=True)
            (live_dir / "broker.conf").write_text("listener 1883\n", encoding="utf-8")
            (live_dir / "acl_compiled.conf").write_text("topic readwrite #\n", encoding="utf-8")
            (live_dir / "passwords.conf").write_text("user:$7$hash\n", encoding="utf-8")
            boundary = DockerMosquittoRuntimeBoundary(
                live_dir=str(live_dir),
                data_dir=str(data_dir),
                log_dir=str(log_dir),
                container_name="synthia-mqtt-broker-test-recreate",
            )
            calls: list[list[str]] = []
            running = {"value": True}

            def _fake_cmd(args: list[str]):
                calls.append(list(args))
                cmd = " ".join(args)
                if cmd.startswith("ps -a"):
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout="synthia-mqtt-broker-test-recreate\n", stderr="")
                if cmd.startswith("ps --"):
                    out = "synthia-mqtt-broker-test-recreate\n" if running["value"] else ""
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout=out, stderr="")
                if cmd.startswith("inspect --format"):
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout='{"1883/tcp":null,"1884/tcp":null}', stderr="")
                if cmd.startswith("rm -f"):
                    running["value"] = False
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout="removed\n", stderr="")
                if cmd.startswith("run "):
                    return subprocess.CompletedProcess(["docker", *args], 0, stdout="containerid\n", stderr="")
                return subprocess.CompletedProcess(["docker", *args], 0, stdout="", stderr="")

            with patch.object(boundary, "_docker_available", return_value=True):
                with patch.object(boundary, "_can_connect", return_value=False):
                    with patch.object(boundary, "_docker_cmd", side_effect=_fake_cmd):
                        status = asyncio.run(boundary.ensure_running())

            self.assertFalse(status.healthy)
            self.assertTrue(any(call and call[0] == "rm" for call in calls))
            self.assertTrue(any(call and call[0] == "run" for call in calls))


if __name__ == "__main__":
    unittest.main()

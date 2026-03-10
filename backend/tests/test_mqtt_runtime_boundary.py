import asyncio
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
            boundary = DockerMosquittoRuntimeBoundary(
                live_dir=str(live_dir),
                data_dir=str(data_dir),
                log_dir=str(log_dir),
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
            boundary = MosquittoProcessRuntimeBoundary(
                live_dir=str(live_dir),
                data_dir=str(data_dir),
                log_dir=str(log_dir),
            )
            self.assertIsInstance(boundary, DockerMosquittoRuntimeBoundary)


if __name__ == "__main__":
    unittest.main()

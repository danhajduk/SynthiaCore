from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.supervisor import SupervisorDomainService, SupervisorRuntimeRegistrationRequest
from app.supervisor.resource_monitor import SupervisorResourceMonitor
from app.supervisor.runtime_store import SupervisorRuntimeNodesStore
from app.system.runtime import StandaloneRuntimeService


class _MemoryInfo:
    rss = 123456


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    def cpu_percent(self, interval=None) -> float:  # noqa: ANN001
        return 7.5

    def memory_percent(self) -> float:
        return 1.25

    def memory_info(self) -> _MemoryInfo:
        return _MemoryInfo()

    def status(self) -> str:
        return "running"


class TestSupervisorResourceMonitor(unittest.TestCase):
    def _monitor(self) -> SupervisorResourceMonitor:
        return SupervisorResourceMonitor(
            process_factory=lambda pid: _FakeProcess(pid),
            docker_available=lambda: False,
            systemctl_available=lambda: False,
        )

    def _runtime_service(self, services_root: Path) -> StandaloneRuntimeService:
        return StandaloneRuntimeService(
            cmd_runner=lambda _cmd: None,
            services_root_resolver=lambda create=False: services_root,
            service_addon_dir_resolver=lambda addon_id, create=False: services_root / addon_id,
        )

    def test_enriches_service_pid_metrics_and_runtime_aggregate(self) -> None:
        monitor = self._monitor()

        usage, metadata = monitor.enrich(
            {},
            {
                "services": [
                    {"service_id": "api", "pid": 1234},
                    {"service_id": "worker", "pid": 5678},
                ]
            },
        )

        services = metadata["services"]
        self.assertIsInstance(services, list)
        self.assertEqual(services[0]["cpu_percent"], 7.5)
        self.assertEqual(services[0]["mem_percent"], 1.25)
        self.assertEqual(services[0]["rss_bytes"], 123456)
        self.assertEqual(usage["cpu_percent"], 15.0)
        self.assertEqual(usage["mem_percent"], 2.5)
        self.assertEqual(usage["rss_bytes"], 246912)

    def test_resolves_systemd_main_pid_before_sampling(self) -> None:
        def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            self.assertEqual(cmd[:4], ["systemctl", "--user", "show", "hexe-node.service"])
            return subprocess.CompletedProcess(cmd, 0, stdout="4321\n", stderr="")

        monitor = SupervisorResourceMonitor(
            process_factory=lambda pid: _FakeProcess(pid),
            command_runner=runner,
            docker_available=lambda: False,
            systemctl_available=lambda: True,
        )

        usage, metadata = monitor.enrich({}, {"systemd_unit": "hexe-node.service"})

        self.assertEqual(metadata["pid"], 4321)
        self.assertEqual(usage["pid"], 4321)
        self.assertEqual(usage["cpu_percent"], 7.5)

    def test_enriches_docker_container_metrics(self) -> None:
        def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            self.assertEqual(cmd[0:2], ["docker", "stats"])
            return subprocess.CompletedProcess(cmd, 0, stdout="hexe-cloudflared\tabc123\t2.5%\t0.75%\n", stderr="")

        monitor = SupervisorResourceMonitor(
            command_runner=runner,
            docker_available=lambda: True,
            systemctl_available=lambda: False,
        )

        usage, metadata = monitor.enrich({}, {"containers": [{"name": "hexe-cloudflared"}]})

        self.assertEqual(metadata["containers"][0]["cpu_percent"], 2.5)
        self.assertEqual(metadata["containers"][0]["mem_percent"], 0.75)
        self.assertEqual(usage["cpu_percent"], 2.5)
        self.assertEqual(usage["mem_percent"], 0.75)

    def test_gpu_summary_samples_nvidia_smi(self) -> None:
        def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            if cmd == ["nvcc", "--version"]:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="0, NVIDIA RTX, GPU-abc, 42, 24576, 6144, 55, 123.4, 170.0\n",
                stderr="",
            )

        monitor = SupervisorResourceMonitor(
            command_runner=runner,
            docker_available=lambda: False,
            systemctl_available=lambda: False,
            gpu_available=lambda: True,
        )

        summary = monitor.gpu_summary()

        self.assertEqual(summary["gpu_count"], 1)
        self.assertEqual(summary["cuda_available"], True)
        self.assertEqual(summary["gpu_utilization_percent"], 42.0)
        self.assertEqual(summary["gpu_memory_percent"], 25.0)
        device = summary["gpu_devices"][0]
        self.assertEqual(device["name"], "NVIDIA RTX")
        self.assertEqual(device["memory_used_mib"], 6144)
        self.assertEqual(device["power_limit_w"], 170.0)

    def test_gpu_summary_reports_cuda_version_from_nvidia_smi(self) -> None:
        def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            if cmd == ["nvcc", "--version"]:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
            if cmd == ["nvidia-smi"]:
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout="| NVIDIA-SMI 550.54.15    Driver Version: 550.54.15    CUDA Version: 12.4     |\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="0, NVIDIA RTX, GPU-abc, 42, 24576, 6144, 55, 123.4, 170.0\n",
                stderr="",
            )

        monitor = SupervisorResourceMonitor(
            command_runner=runner,
            docker_available=lambda: False,
            systemctl_available=lambda: False,
            gpu_available=lambda: True,
        )

        summary = monitor.gpu_summary()

        self.assertEqual(summary["cuda_available"], True)
        self.assertEqual(summary["cuda_version"], "12.4")

    def test_info_summary_uses_configured_supervisor_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = SupervisorDomainService(self._runtime_service(Path(tmpdir) / "services"))
            with patch.dict("os.environ", {"HEXE_SUPERVISOR_ID": "local-core-supervisor"}, clear=False):
                summary = service.info_summary()

        self.assertEqual(summary.supervisor_id, "local-core-supervisor")

    def test_registered_runtime_summary_prefers_supervisor_sampled_service_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtimes = SupervisorRuntimeNodesStore(path=root / "supervisor_runtime_nodes.json")
            service = SupervisorDomainService(
                self._runtime_service(root / "services"),
                runtimes,
                resource_monitor=self._monitor(),
            )
            service.register_runtime(
                SupervisorRuntimeRegistrationRequest(
                    node_id="node-1",
                    node_name="AI Node",
                    node_type="ai",
                    resource_usage={"cpu_percent": 99.0},
                    runtime_metadata={"services": [{"service_id": "worker", "pid": 1234}]},
                )
            )

            summary = service.get_registered_runtime("node-1")

        self.assertEqual(summary.resource_usage["cpu_percent"], 7.5)
        self.assertEqual(summary.resource_usage["mem_percent"], 1.25)
        services = summary.runtime_metadata["services"]
        self.assertEqual(services[0]["cpu_percent"], 7.5)
        self.assertEqual(services[0]["resource_source"], "supervisor_pid")


if __name__ == "__main__":
    unittest.main()

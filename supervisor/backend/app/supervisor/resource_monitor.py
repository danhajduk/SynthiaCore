from __future__ import annotations

import copy
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import psutil


class SupervisorResourceMonitor:
    """Samples host-local resources for Supervisor-owned runtime identities."""

    def __init__(
        self,
        *,
        process_factory: Callable[[int], Any] | None = None,
        command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
        docker_available: Callable[[], bool] | None = None,
        systemctl_available: Callable[[], bool] | None = None,
        gpu_available: Callable[[], bool] | None = None,
    ) -> None:
        self._process_factory = process_factory or psutil.Process
        self._command_runner = command_runner or self._run_command
        self._docker_available = docker_available or (lambda: shutil.which("docker") is not None)
        self._systemctl_available = systemctl_available or (lambda: shutil.which("systemctl") is not None)
        self._gpu_available = gpu_available or (lambda: shutil.which("nvidia-smi") is not None)

    def enrich(
        self,
        resource_usage: dict[str, object] | None,
        runtime_metadata: dict[str, object] | None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        usage = dict(resource_usage or {})
        metadata = copy.deepcopy(runtime_metadata or {})
        metadata.setdefault("resource_observer", "supervisor")

        top_metrics = self._sample_target(metadata)
        if top_metrics:
            self._merge_metrics(usage, top_metrics)

        service_metrics = self._enrich_services(metadata.get("services"))
        container_metrics = self._enrich_containers(metadata.get("containers"))

        aggregate = self._aggregate_metrics([*service_metrics, *container_metrics])
        if aggregate:
            self._merge_metrics(usage, aggregate)

        if "sampled_at" not in usage and (top_metrics or aggregate):
            usage["sampled_at"] = self._now_iso()
            usage.setdefault("resource_observer", "supervisor")
        return usage, metadata

    def _run_command(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5.0, check=False)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def gpu_summary(self) -> dict[str, object]:
        devices = self._nvidia_gpu_devices()
        if not devices:
            return {"gpu_count": 0, "gpu_devices": [], "cuda_available": False}

        util_values = [float(item["utilization_percent"]) for item in devices if isinstance(item.get("utilization_percent"), int | float)]
        mem_values = [float(item["memory_percent"]) for item in devices if isinstance(item.get("memory_percent"), int | float)]
        summary: dict[str, object] = {
            "gpu_count": len(devices),
            "gpu_devices": devices,
            "cuda_available": True,
        }
        cuda_version = self._nvidia_cuda_version() or self._nvcc_cuda_version()
        if cuda_version:
            summary["cuda_version"] = cuda_version
        if util_values:
            summary["gpu_utilization_percent"] = sum(util_values) / len(util_values)
        if mem_values:
            summary["gpu_memory_percent"] = sum(mem_values) / len(mem_values)
        return summary

    def _nvidia_cuda_version(self) -> str | None:
        try:
            result = self._command_runner(["nvidia-smi"])
        except Exception:
            return None
        if result.returncode != 0:
            return None
        marker = "CUDA Version:"
        for line in (result.stdout or "").splitlines():
            if marker not in line:
                continue
            version = line.split(marker, 1)[1].strip().split()[0].strip()
            return version if version and version.upper() not in {"N/A", "NA"} else None
        return None

    def _nvcc_cuda_version(self) -> str | None:
        if shutil.which("nvcc") is None:
            return None
        try:
            result = self._command_runner(["nvcc", "--version"])
        except Exception:
            return None
        if result.returncode != 0:
            return None
        text = result.stdout or ""
        marker = "release "
        if marker not in text:
            return None
        version = text.split(marker, 1)[1].split(",", 1)[0].strip()
        return version or None

    def _nvidia_gpu_devices(self) -> list[dict[str, object]]:
        if not self._gpu_available():
            return []
        try:
            result = self._command_runner(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,uuid,utilization.gpu,memory.total,memory.used,temperature.gpu,power.draw",
                    "--format=csv,noheader,nounits",
                ]
            )
        except Exception:
            return []
        if result.returncode != 0:
            return []

        devices: list[dict[str, object]] = []
        for line in (result.stdout or "").splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 8:
                continue
            index_raw, name, uuid, util_raw, mem_total_raw, mem_used_raw, temp_raw, power_raw = parts[:8]
            device: dict[str, object] = {
                "index": self._parse_int(index_raw),
                "name": name,
                "uuid": uuid,
                "resource_source": "nvidia_smi",
                "sampled_at": self._now_iso(),
            }
            util = self._parse_float(util_raw)
            mem_total = self._parse_int(mem_total_raw)
            mem_used = self._parse_int(mem_used_raw)
            temp = self._parse_float(temp_raw)
            power = self._parse_float(power_raw)
            if util is not None:
                device["utilization_percent"] = util
            if mem_total is not None:
                device["memory_total_mib"] = mem_total
            if mem_used is not None:
                device["memory_used_mib"] = mem_used
            if mem_total and mem_used is not None:
                device["memory_percent"] = min(max((float(mem_used) / float(mem_total)) * 100.0, 0.0), 100.0)
            if temp is not None:
                device["temperature_c"] = temp
            if power is not None:
                device["power_w"] = power
            devices.append({key: value for key, value in device.items() if value is not None})
        return devices

    def _parse_float(self, value: object) -> float | None:
        try:
            text = str(value).strip()
            if not text or text.upper() in {"N/A", "NA"}:
                return None
            return float(text)
        except Exception:
            return None

    def _parse_int(self, value: object) -> int | None:
        parsed = self._parse_float(value)
        if parsed is None:
            return None
        return int(parsed)

    def _as_pid(self, value: object) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            pid = int(value)  # type: ignore[arg-type]
        except Exception:
            return None
        return pid if pid > 0 else None

    def _first_text(self, target: dict[str, object], keys: list[str]) -> str | None:
        for key in keys:
            value = target.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _process_metrics(self, pid: int) -> dict[str, object]:
        try:
            proc = self._process_factory(pid)
            try:
                cpu_percent = float(proc.cpu_percent(interval=None))
            except Exception:
                cpu_percent = None
            try:
                mem_percent = float(proc.memory_percent())
            except Exception:
                mem_percent = None
            try:
                rss_bytes = int(proc.memory_info().rss)
            except Exception:
                rss_bytes = None
            try:
                status = str(proc.status())
            except Exception:
                status = None
            metrics: dict[str, object] = {
                "pid": pid,
                "resource_source": "supervisor_pid",
                "sampled_at": self._now_iso(),
            }
            if cpu_percent is not None:
                metrics["cpu_percent"] = cpu_percent
            if mem_percent is not None:
                metrics["mem_percent"] = mem_percent
            if rss_bytes is not None:
                metrics["rss_bytes"] = rss_bytes
            if status:
                metrics["process_status"] = status
            return metrics
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            return {
                "pid": pid,
                "running": False,
                "resource_source": "supervisor_pid",
                "last_error": "process_unavailable",
                "sampled_at": self._now_iso(),
            }
        except Exception as exc:
            return {
                "pid": pid,
                "resource_source": "supervisor_pid",
                "last_error": str(exc) or type(exc).__name__,
                "sampled_at": self._now_iso(),
            }

    def _systemd_main_pid(self, unit: str) -> int | None:
        if not self._systemctl_available():
            return None
        try:
            result = self._command_runner(["systemctl", "--user", "show", unit, "--property=MainPID", "--value"])
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return self._as_pid(str(result.stdout or "").strip())

    def _docker_stats(self, identifiers: list[str]) -> dict[str, dict[str, object]]:
        names = [item for item in dict.fromkeys(str(value or "").strip() for value in identifiers) if item]
        if not names or not self._docker_available():
            return {}
        try:
            result = self._command_runner(
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{.Name}}\t{{.ID}}\t{{.CPUPerc}}\t{{.MemPerc}}",
                    *names,
                ]
            )
        except Exception:
            return {}
        if result.returncode != 0:
            return {}
        stats: dict[str, dict[str, object]] = {}
        for line in (result.stdout or "").splitlines():
            parts = [chunk.strip() for chunk in line.split("\t")]
            if len(parts) < 4:
                continue
            name, container_id, cpu_raw, mem_raw = parts[0], parts[1], parts[2], parts[3]
            metrics: dict[str, object] = {
                "container_name": name,
                "container_id": container_id,
                "resource_source": "supervisor_docker",
                "sampled_at": self._now_iso(),
            }
            try:
                metrics["cpu_percent"] = float(cpu_raw.replace("%", "").strip())
            except Exception:
                pass
            try:
                metrics["mem_percent"] = float(mem_raw.replace("%", "").strip())
            except Exception:
                pass
            stats[name] = metrics
            if container_id:
                stats[container_id] = metrics
        return stats

    def _sample_container(self, target: dict[str, object]) -> dict[str, object]:
        identifier = self._first_text(target, ["container_name", "container_id", "name"])
        if not identifier:
            return {}
        return dict(self._docker_stats([identifier]).get(identifier) or {})

    def _sample_target(self, target: object) -> dict[str, object]:
        if not isinstance(target, dict):
            return {}

        pid = self._as_pid(target.get("pid"))
        process = target.get("process")
        if pid is None and isinstance(process, dict):
            pid = self._as_pid(process.get("pid"))

        systemd_unit = self._first_text(target, ["systemd_unit", "systemd_service"])
        if pid is None and systemd_unit:
            pid = self._systemd_main_pid(systemd_unit)
            if pid is not None:
                target["pid"] = pid

        if pid is not None:
            metrics = self._process_metrics(pid)
            self._merge_metrics(target, metrics)
            if systemd_unit:
                target.setdefault("resource_source", "supervisor_systemd_pid")
                metrics.setdefault("resource_source", "supervisor_systemd_pid")
            return metrics

        container_metrics = self._sample_container(target)
        if container_metrics:
            self._merge_metrics(target, container_metrics)
        return container_metrics

    def _enrich_services(self, services: object) -> list[dict[str, object]]:
        metrics: list[dict[str, object]] = []
        if isinstance(services, list):
            for item in services:
                sampled = self._sample_target(item)
                if sampled:
                    metrics.append(sampled)
        elif isinstance(services, dict):
            for item in services.values():
                sampled = self._sample_target(item)
                if sampled:
                    metrics.append(sampled)
        return metrics

    def _enrich_containers(self, containers: object) -> list[dict[str, object]]:
        metrics: list[dict[str, object]] = []
        if not isinstance(containers, list):
            return metrics
        identifiers: list[str] = []
        for item in containers:
            if isinstance(item, dict):
                identifier = self._first_text(item, ["container_name", "container_id", "name"])
                if identifier:
                    identifiers.append(identifier)
        stats = self._docker_stats(identifiers)
        for item in containers:
            if not isinstance(item, dict):
                continue
            identifier = self._first_text(item, ["container_name", "container_id", "name"])
            sampled = dict(stats.get(identifier or "") or {})
            if sampled:
                self._merge_metrics(item, sampled)
                metrics.append(sampled)
        return metrics

    def _merge_metrics(self, target: dict[str, object], metrics: dict[str, object]) -> None:
        for key, value in metrics.items():
            if value is not None:
                target[key] = value

    def _aggregate_metrics(self, entries: list[dict[str, object]]) -> dict[str, object]:
        if not entries:
            return {}
        cpu_total = 0.0
        mem_total = 0.0
        rss_total = 0
        cpu_seen = False
        mem_seen = False
        rss_seen = False
        for entry in entries:
            cpu = entry.get("cpu_percent")
            mem = entry.get("mem_percent")
            rss = entry.get("rss_bytes")
            if isinstance(cpu, int | float):
                cpu_total += float(cpu)
                cpu_seen = True
            if isinstance(mem, int | float):
                mem_total += float(mem)
                mem_seen = True
            if isinstance(rss, int):
                rss_total += rss
                rss_seen = True
        aggregate: dict[str, object] = {
            "resource_source": "supervisor_aggregate",
            "sampled_at": self._now_iso(),
        }
        if cpu_seen:
            aggregate["cpu_percent"] = cpu_total
        if mem_seen:
            aggregate["mem_percent"] = mem_total
        if rss_seen:
            aggregate["rss_bytes"] = rss_total
        return aggregate

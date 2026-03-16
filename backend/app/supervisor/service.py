from __future__ import annotations

import os
import socket
import json
from typing import Any
from pathlib import Path

from app.system.runtime import StandaloneRuntimeService
from app.system.stats.models import SystemStats, SystemStatsSnapshot
from app.system.stats.service import collect_process_stats, collect_system_snapshot, collect_system_stats
from synthia_supervisor.docker_compose import compose_down, compose_up

from .models import (
    HostIdentitySummary,
    HostResourceSummary,
    ManagedNodeSummary,
    ProcessResourceSummary,
    SupervisorHealthSummary,
    SupervisorInfoSummary,
    SupervisorNodeActionResult,
    SupervisorOwnershipBoundary,
    SupervisorRuntimeSummary,
)


class SupervisorDomainService:
    def __init__(self, runtime_service: StandaloneRuntimeService | None = None) -> None:
        self._runtime_service = runtime_service or StandaloneRuntimeService()

    def _runtime_provider(self) -> str:
        return str(os.getenv("SYNTHIA_MQTT_RUNTIME_PROVIDER", "docker")).strip().lower() or "docker"

    def _host_identity(self) -> HostIdentitySummary:
        hostname = socket.gethostname()
        return HostIdentitySummary(
            host_id=hostname,
            hostname=hostname,
            runtime_provider=self._runtime_provider(),
        )

    def _host_resources(self) -> HostResourceSummary:
        stats = collect_system_stats(api_metrics=None)
        root_disk = stats.disks.get("/")
        return HostResourceSummary(
            uptime_s=stats.uptime_s,
            load_1m=stats.load.load1,
            load_5m=stats.load.load5,
            load_15m=stats.load.load15,
            cpu_percent_total=stats.cpu.percent_total,
            cpu_cores_logical=stats.cpu.cores_logical,
            memory_total_bytes=stats.mem.total,
            memory_available_bytes=stats.mem.available,
            memory_percent=stats.mem.percent,
            root_disk_total_bytes=root_disk.total if root_disk is not None else None,
            root_disk_free_bytes=root_disk.free if root_disk is not None else None,
            root_disk_percent=root_disk.percent if root_disk is not None else None,
        )

    def _managed_nodes(self) -> list[ManagedNodeSummary]:
        runtimes = self._runtime_service.list_standalone_addon_runtimes()
        return [
            ManagedNodeSummary(
                node_id=item.addon_id,
                desired_state=item.desired_state,
                runtime_state=item.runtime_state,
                health_status=item.health_status,
                active_version=item.active_version,
                running=item.running,
            )
            for item in runtimes
        ]

    def system_stats(self, *, api_metrics=None) -> SystemStats:
        return collect_system_stats(api_metrics=api_metrics)

    def system_snapshot(
        self,
        *,
        api_metrics=None,
        api_snapshot: dict[str, Any] | None = None,
        registry=None,
        quiet_thresholds=None,
    ) -> SystemStatsSnapshot:
        return collect_system_snapshot(
            api_metrics=api_metrics,
            api_snapshot=api_snapshot,
            registry=registry,
            quiet_thresholds=quiet_thresholds,
        )

    def process_stats(self) -> dict[str, Any]:
        return collect_process_stats()

    def process_summary(self) -> ProcessResourceSummary:
        stats = self.process_stats()
        return ProcessResourceSummary(
            rss_bytes=stats.get("rss_bytes"),
            cpu_percent=stats.get("cpu_percent"),
            open_fds=stats.get("open_fds"),
            threads=stats.get("threads"),
        )

    def resources_summary(self) -> HostResourceSummary:
        return self._host_resources()

    def runtime_summary(self) -> SupervisorRuntimeSummary:
        managed_nodes = self._managed_nodes()
        return SupervisorRuntimeSummary(
            host=self._host_identity(),
            resources=self._host_resources(),
            process=self.process_summary(),
            managed_node_count=len(managed_nodes),
            managed_nodes=managed_nodes,
        )

    def list_managed_nodes(self) -> list[ManagedNodeSummary]:
        return self._managed_nodes()

    def _runtime_snapshot(self, node_id: str):
        return self._runtime_service.get_standalone_addon_runtime_snapshot(node_id)

    def _compose_files_for_snapshot(self, snapshot) -> list[Path]:
        raw_runtime = snapshot.raw_runtime if isinstance(snapshot.raw_runtime, dict) else {}
        compose_files = raw_runtime.get("compose_files_in_use")
        if isinstance(compose_files, list):
            paths = [Path(item) for item in compose_files if isinstance(item, str) and item.strip()]
            if paths:
                return paths
        desired_path = Path(snapshot.desired_path)
        current_compose = desired_path.parent / "current" / "docker-compose.yml"
        version_compose = desired_path.parent / "versions" / str(snapshot.runtime.active_version or "").strip() / "docker-compose.yml"
        if current_compose.exists():
            return [current_compose]
        if version_compose.exists():
            return [version_compose]
        raise ValueError("compose_files_unavailable")

    def _project_name_for_snapshot(self, snapshot) -> str:
        raw_desired = snapshot.raw_desired if isinstance(snapshot.raw_desired, dict) else {}
        runtime_cfg = raw_desired.get("runtime") if isinstance(raw_desired.get("runtime"), dict) else {}
        project_name = str(runtime_cfg.get("project_name") or "").strip()
        if not project_name:
            raise ValueError("project_name_unavailable")
        return project_name

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _set_desired_state(self, snapshot, desired_state: str) -> None:
        if not isinstance(snapshot.raw_desired, dict):
            return
        payload = dict(snapshot.raw_desired)
        payload["desired_state"] = desired_state
        self._write_json(Path(snapshot.desired_path), payload)

    def _set_runtime_state(self, snapshot, runtime_state: str) -> None:
        payload = dict(snapshot.raw_runtime) if isinstance(snapshot.raw_runtime, dict) else {}
        payload["state"] = runtime_state
        payload.pop("error", None)
        payload.pop("last_error", None)
        self._write_json(Path(snapshot.runtime_path), payload)

    def _action_result(self, action: str, node_id: str) -> SupervisorNodeActionResult:
        node = next((item for item in self._managed_nodes() if item.node_id == node_id), None)
        if node is None:
            snapshot = self._runtime_snapshot(node_id)
            node = ManagedNodeSummary(
                node_id=snapshot.runtime.addon_id,
                desired_state=snapshot.runtime.desired_state,
                runtime_state=snapshot.runtime.runtime_state,
                health_status=snapshot.runtime.health_status,
                active_version=snapshot.runtime.active_version,
                running=snapshot.runtime.running,
            )
        return SupervisorNodeActionResult(action=action, node=node)

    def start_managed_node(self, node_id: str) -> SupervisorNodeActionResult:
        snapshot = self._runtime_snapshot(node_id)
        compose_files = self._compose_files_for_snapshot(snapshot)
        project_name = self._project_name_for_snapshot(snapshot)
        self._set_desired_state(snapshot, "running")
        compose_up(compose_files, project_name)
        self._set_runtime_state(snapshot, "running")
        return self._action_result("start", node_id)

    def stop_managed_node(self, node_id: str) -> SupervisorNodeActionResult:
        snapshot = self._runtime_snapshot(node_id)
        compose_files = self._compose_files_for_snapshot(snapshot)
        project_name = self._project_name_for_snapshot(snapshot)
        self._set_desired_state(snapshot, "stopped")
        compose_down(compose_files, project_name)
        self._set_runtime_state(snapshot, "stopped")
        return self._action_result("stop", node_id)

    def restart_managed_node(self, node_id: str) -> SupervisorNodeActionResult:
        snapshot = self._runtime_snapshot(node_id)
        compose_files = self._compose_files_for_snapshot(snapshot)
        project_name = self._project_name_for_snapshot(snapshot)
        self._set_desired_state(snapshot, "running")
        compose_down(compose_files, project_name)
        compose_up(compose_files, project_name)
        self._set_runtime_state(snapshot, "running")
        return self._action_result("restart", node_id)

    def health_summary(self) -> SupervisorHealthSummary:
        managed_nodes = self._managed_nodes()
        healthy = sum(1 for item in managed_nodes if str(item.health_status or "").strip().lower() == "healthy")
        unhealthy = sum(1 for item in managed_nodes if str(item.health_status or "").strip().lower() == "unhealthy")
        return SupervisorHealthSummary(
            status="ok",
            host=self._host_identity(),
            resources=self._host_resources(),
            managed_node_count=len(managed_nodes),
            healthy_node_count=healthy,
            unhealthy_node_count=unhealthy,
        )

    def info_summary(self) -> SupervisorInfoSummary:
        managed_nodes = self._managed_nodes()
        host = self._host_identity()
        return SupervisorInfoSummary(
            supervisor_id=host.host_id,
            host=host,
            resources=self._host_resources(),
            boundaries=SupervisorOwnershipBoundary(
                owns=[
                    "host-local standalone runtime realization",
                    "desired-to-runtime reconciliation",
                    "standalone workload lifecycle execution",
                ],
                depends_on_core_for=[
                    "global governance and scheduler policy",
                    "node trust and onboarding authority",
                    "operator UI and control-plane APIs",
                ],
            ),
            managed_node_count=len(managed_nodes),
            managed_nodes=managed_nodes,
        )

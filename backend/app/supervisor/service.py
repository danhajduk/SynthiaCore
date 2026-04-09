from __future__ import annotations

import os
import socket
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any
from pathlib import Path

import httpx
from fastapi import HTTPException

from app.system.onboarding import NodeRegistrationsStore
from app.system.runtime import StandaloneRuntimeService
from app.system.stats.models import SystemStats, SystemStatsSnapshot
from app.system.stats.service import collect_process_stats, collect_system_snapshot, collect_system_stats
from synthia_supervisor.docker_compose import compose_down, compose_up

from .models import (
    HostIdentitySummary,
    HostResourceSummary,
    ManagedNodeSummary,
    ProcessResourceSummary,
    SupervisorAdmissionContextSummary,
    SupervisorCoreRuntimeActionResult,
    SupervisorCoreRuntimeHeartbeatRequest,
    SupervisorCoreRuntimeRegistrationRequest,
    SupervisorCoreRuntimeSummary,
    SupervisorHealthSummary,
    SupervisorInfoSummary,
    SupervisorNodeActionResult,
    SupervisorNodeServiceActionResult,
    SupervisorNodeServiceSummary,
    SupervisorNodeServicesSummary,
    SupervisorOwnershipBoundary,
    SupervisorRegisteredRuntimeSummary,
    SupervisorRuntimeActionResult,
    SupervisorRuntimeHeartbeatRequest,
    SupervisorRuntimeRegistrationRequest,
    SupervisorRuntimeSummary,
)
from .boot_order import load_boot_order_plan
from .core_runtime_store import SupervisorCoreRuntimeRecord, SupervisorCoreRuntimeStore
from .runtime_nodes import merge_runtime_identity
from .runtime_store import SupervisorRuntimeNodeRecord, SupervisorRuntimeNodesStore


class SupervisorDomainService:
    def __init__(
        self,
        runtime_service: StandaloneRuntimeService | None = None,
        runtime_nodes_store: SupervisorRuntimeNodesStore | None = None,
        core_runtime_store: SupervisorCoreRuntimeStore | None = None,
        node_registrations_store: NodeRegistrationsStore | None = None,
    ) -> None:
        self._runtime_service = runtime_service or StandaloneRuntimeService()
        self._runtime_nodes_store = runtime_nodes_store or SupervisorRuntimeNodesStore()
        self._core_runtime_store = core_runtime_store or SupervisorCoreRuntimeStore()
        self._node_registrations_store = node_registrations_store
        self._boot_loop_status: dict[str, Any] = {
            "state": "idle",
            "updated_at": self._now_iso(),
        }

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
                lifecycle_state=item.lifecycle_state,
                desired_state=item.desired_state,
                runtime_state=item.runtime_state,
                health_status=item.health_status,
                active_version=item.active_version,
                running=item.running,
                last_action=item.last_action,
                last_action_at=item.last_action_at,
            )
            for item in runtimes
        ]

    def _runtime_stale_after_s(self) -> int:
        raw = str(os.getenv("SYNTHIA_SUPERVISOR_NODE_HEARTBEAT_STALE_S", "60")).strip()
        try:
            parsed = int(raw)
        except Exception:
            return 60
        return max(1, parsed)

    def _runtime_offline_after_s(self) -> int:
        raw = str(os.getenv("SYNTHIA_SUPERVISOR_NODE_HEARTBEAT_OFFLINE_S", "180")).strip()
        try:
            parsed = int(raw)
        except Exception:
            return 180
        return max(self._runtime_stale_after_s() + 1, parsed)

    def _resolve_node_api_base_url(self, node_id: str) -> str:
        runtime = self._runtime_nodes_store.get(node_id)
        base_url = str(runtime.api_base_url or "").strip() if runtime is not None else ""
        if not base_url and self._node_registrations_store is not None:
            record = self._node_registrations_store.get(node_id)
            if record is not None:
                base_url = str(record.api_base_url or "").strip()
        if not base_url:
            raise HTTPException(status_code=412, detail="node_api_base_url_missing")
        if not base_url.startswith("http"):
            raise HTTPException(status_code=400, detail="node_api_base_url_invalid")
        return base_url.rstrip("/")

    def _node_api_request(self, node_id: str, *, method: str, path: str, payload: dict | None = None) -> dict:
        base_url = self._resolve_node_api_base_url(node_id)
        url = f"{base_url}{path}"
        try:
            with httpx.Client(timeout=4.0) as client:
                response = client.request(method.upper(), url, json=payload)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"node_api_unreachable: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text.strip() or response.reason_phrase
            raise HTTPException(status_code=502, detail=f"node_api_error: {response.status_code} {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="node_api_invalid_json") from exc

    def _normalize_node_services(self, payload: dict) -> list[SupervisorNodeServiceSummary]:
        services_raw = payload.get("services")
        if not isinstance(services_raw, dict):
            return []
        normalized: list[SupervisorNodeServiceSummary] = []
        for service_id, value in services_raw.items():
            if isinstance(value, dict):
                state = str(value.get("state") or value.get("status") or value.get("service_state") or "unknown")
                normalized.append(
                    SupervisorNodeServiceSummary(
                        service_id=str(service_id),
                        service_name=str(value.get("service_name") or value.get("name") or service_id),
                        service_state=state,
                        desired_state=str(value.get("desired_state") or "") or None,
                        health_status=str(value.get("health_status") or "") or None,
                        updated_at=str(value.get("updated_at") or "") or None,
                        metadata={k: v for k, v in value.items() if k not in {"state", "status", "service_state"}},
                    )
                )
            else:
                normalized.append(
                    SupervisorNodeServiceSummary(
                        service_id=str(service_id),
                        service_name=str(service_id),
                        service_state=str(value or "unknown"),
                    )
                )
        return normalized

    def node_services_status(self, node_id: str) -> SupervisorNodeServicesSummary:
        payload = self._node_api_request(node_id, method="GET", path="/api/services/status")
        return SupervisorNodeServicesSummary(
            node_id=node_id,
            api_base_url=self._resolve_node_api_base_url(node_id),
            services=self._normalize_node_services(payload),
        )

    def node_service_action(self, node_id: str, *, service_id: str, action: str) -> SupervisorNodeServiceActionResult:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"start", "stop", "restart"}:
            raise HTTPException(status_code=400, detail="unsupported_service_action")
        self._append_boot_log(
            "service_action",
            context={"runtime_id": node_id, "service_id": service_id, "action": normalized_action},
        )
        payload = {"target": service_id}
        response = self._node_api_request(node_id, method="POST", path=f"/api/services/{normalized_action}", payload=payload)
        return SupervisorNodeServiceActionResult(
            action=normalized_action,
            node_id=node_id,
            service_id=str(service_id),
            result=response if isinstance(response, dict) else {"response": response},
        )

    def _freshness_state(self, last_seen_at: str | None, *, health_status: str, runtime_state: str) -> str:
        if str(runtime_state or "").strip().lower() == "error" or str(health_status or "").strip().lower() == "error":
            return "error"
        if not last_seen_at:
            return "offline"
        try:
            seen = datetime.fromisoformat(str(last_seen_at).replace("Z", "+00:00"))
        except Exception:
            return "offline"
        age_s = max(0.0, (datetime.now(timezone.utc) - seen).total_seconds())
        if age_s >= self._runtime_offline_after_s():
            return "offline"
        if age_s >= self._runtime_stale_after_s():
            return "stale"
        return "online"

    def _core_runtime_heartbeat_interval_s(self) -> float:
        raw = str(os.getenv("HEXE_SUPERVISOR_CORE_HEARTBEAT_S", "5")).strip()
        try:
            parsed = float(raw)
        except Exception:
            return 5.0
        return max(1.0, parsed)

    def _core_runtime_stale_after_s(self) -> float:
        raw = str(os.getenv("HEXE_SUPERVISOR_CORE_HEARTBEAT_STALE_S", "")).strip()
        if raw:
            try:
                parsed = float(raw)
                return max(1.0, parsed)
            except Exception:
                pass
        return max(1.0, self._core_runtime_heartbeat_interval_s() * 2)

    def _core_runtime_offline_after_s(self) -> float:
        raw = str(os.getenv("HEXE_SUPERVISOR_CORE_HEARTBEAT_OFFLINE_S", "")).strip()
        if raw:
            try:
                parsed = float(raw)
                return max(self._core_runtime_stale_after_s() + 1.0, parsed)
            except Exception:
                pass
        return max(self._core_runtime_stale_after_s() + 1.0, self._core_runtime_heartbeat_interval_s() * 5)

    def _core_freshness_state(self, last_seen_at: str | None, *, health_status: str, runtime_state: str) -> str:
        if str(runtime_state or "").strip().lower() == "error" or str(health_status or "").strip().lower() == "error":
            return "error"
        if not last_seen_at:
            return "offline"
        try:
            seen = datetime.fromisoformat(str(last_seen_at).replace("Z", "+00:00"))
        except Exception:
            return "offline"
        age_s = max(0.0, (datetime.now(timezone.utc) - seen).total_seconds())
        if age_s >= self._core_runtime_offline_after_s():
            return "offline"
        if age_s >= self._core_runtime_stale_after_s():
            return "stale"
        return "online"

    def _registered_runtime_summary(self, record: SupervisorRuntimeNodeRecord) -> SupervisorRegisteredRuntimeSummary:
        merged = merge_runtime_identity(record, self._node_registrations_store)
        return SupervisorRegisteredRuntimeSummary(
            node_id=merged.node_id,
            node_name=merged.node_name,
            node_type=merged.node_type,
            desired_state=merged.desired_state,
            runtime_state=merged.runtime_state,
            lifecycle_state=merged.lifecycle_state,
            health_status=merged.health_status,
            freshness_state=self._freshness_state(
                merged.last_seen_at,
                health_status=merged.health_status,
                runtime_state=merged.runtime_state,
            ),
            host_id=merged.host_id,
            hostname=merged.hostname,
            api_base_url=merged.api_base_url,
            ui_base_url=merged.ui_base_url,
            health_detail=merged.health_detail,
            registered_at=merged.registered_at,
            updated_at=merged.updated_at,
            last_seen_at=merged.last_seen_at,
            last_action=merged.last_action,
            last_action_at=merged.last_action_at,
            last_error=merged.last_error,
            running=merged.running,
            resource_usage=dict(merged.resource_usage or {}),
            runtime_metadata=dict(merged.runtime_metadata or {}),
        )

    def list_registered_runtimes(self) -> list[SupervisorRegisteredRuntimeSummary]:
        return [self._registered_runtime_summary(item) for item in self._runtime_nodes_store.list()]

    def get_registered_runtime(self, node_id: str) -> SupervisorRegisteredRuntimeSummary:
        record = self._runtime_nodes_store.get(node_id)
        if record is None:
            raise HTTPException(status_code=404, detail="runtime_not_registered")
        return self._registered_runtime_summary(record)

    def register_runtime(self, payload: SupervisorRuntimeRegistrationRequest) -> SupervisorRegisteredRuntimeSummary:
        record = self._runtime_nodes_store.upsert_registration(payload=payload.model_dump())
        return self._registered_runtime_summary(record)

    def heartbeat_runtime(self, payload: SupervisorRuntimeHeartbeatRequest) -> SupervisorRegisteredRuntimeSummary:
        record = self._runtime_nodes_store.apply_heartbeat(payload.node_id, payload=payload.model_dump())
        if record is None:
            raise HTTPException(status_code=404, detail="runtime_not_registered")
        return self._registered_runtime_summary(record)

    def _registered_runtime_action(
        self,
        node_id: str,
        *,
        action: str,
        desired_state: str,
        lifecycle_state: str,
    ) -> SupervisorRuntimeActionResult:
        self._append_boot_log(
            "runtime_action",
            context={
                "runtime_id": node_id,
                "action": action,
                "scope": "registered_runtime",
                "message": f"{action.capitalize()} {node_id}",
            },
        )
        record = self._runtime_nodes_store.apply_action(
            node_id,
            action=action,
            desired_state=desired_state,
            lifecycle_state=lifecycle_state,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="runtime_not_registered")
        return SupervisorRuntimeActionResult(action=action, runtime=self._registered_runtime_summary(record))

    def start_registered_runtime(self, node_id: str) -> SupervisorRuntimeActionResult:
        return self._registered_runtime_action(
            node_id,
            action="start",
            desired_state="running",
            lifecycle_state="starting",
        )

    def stop_registered_runtime(self, node_id: str) -> SupervisorRuntimeActionResult:
        return self._registered_runtime_action(
            node_id,
            action="stop",
            desired_state="stopped",
            lifecycle_state="stopping",
        )

    def restart_registered_runtime(self, node_id: str) -> SupervisorRuntimeActionResult:
        return self._registered_runtime_action(
            node_id,
            action="restart",
            desired_state="running",
            lifecycle_state="restarting",
        )

    def _normalize_core_runtime_kind(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"core", "core_service"}:
            return "core_service"
        if normalized in {"addon", "aux_service", "aux_container"}:
            return normalized
        return normalized or "core_service"

    def _normalize_core_management_mode(self, value: str, *, runtime_kind: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"monitor", "manage"}:
            normalized = "monitor" if runtime_kind == "core_service" else "manage"
        if runtime_kind == "core_service":
            return "monitor"
        return normalized

    def _core_runtime_summary(self, record: SupervisorCoreRuntimeRecord) -> SupervisorCoreRuntimeSummary:
        return SupervisorCoreRuntimeSummary(
            runtime_id=record.runtime_id,
            runtime_name=record.runtime_name,
            runtime_kind=record.runtime_kind,
            management_mode=record.management_mode,
            desired_state=record.desired_state,
            runtime_state=record.runtime_state,
            lifecycle_state=record.lifecycle_state,
            health_status=record.health_status,
            freshness_state=self._core_freshness_state(
                record.last_seen_at,
                health_status=record.health_status,
                runtime_state=record.runtime_state,
            ),
            host_id=record.host_id,
            hostname=record.hostname,
            registered_at=record.registered_at,
            updated_at=record.updated_at,
            last_seen_at=record.last_seen_at,
            last_action=record.last_action,
            last_action_at=record.last_action_at,
            last_error=record.last_error,
            running=record.running,
            resource_usage=dict(record.resource_usage or {}),
            runtime_metadata=dict(record.runtime_metadata or {}),
        )

    def list_core_runtimes(self) -> list[SupervisorCoreRuntimeSummary]:
        return [self._core_runtime_summary(item) for item in self._core_runtime_store.list()]

    def get_core_runtime(self, runtime_id: str) -> SupervisorCoreRuntimeSummary:
        record = self._core_runtime_store.get(runtime_id)
        if record is None:
            raise HTTPException(status_code=404, detail="core_runtime_not_registered")
        return self._core_runtime_summary(record)

    def register_core_runtime(self, payload: SupervisorCoreRuntimeRegistrationRequest) -> SupervisorCoreRuntimeSummary:
        data = payload.model_dump()
        runtime_kind = self._normalize_core_runtime_kind(data.get("runtime_kind"))
        data["runtime_kind"] = runtime_kind
        data["management_mode"] = self._normalize_core_management_mode(data.get("management_mode"), runtime_kind=runtime_kind)
        record = self._core_runtime_store.upsert_registration(payload=data)
        return self._core_runtime_summary(record)

    def heartbeat_core_runtime(self, payload: SupervisorCoreRuntimeHeartbeatRequest) -> SupervisorCoreRuntimeSummary:
        record = self._core_runtime_store.apply_heartbeat(payload.runtime_id, payload=payload.model_dump())
        if record is None:
            raise HTTPException(status_code=404, detail="core_runtime_not_registered")
        return self._core_runtime_summary(record)

    def _core_runtime_action(
        self,
        runtime_id: str,
        *,
        action: str,
        desired_state: str,
        lifecycle_state: str,
    ) -> SupervisorCoreRuntimeActionResult:
        record = self._core_runtime_store.get(runtime_id)
        if record is None:
            raise HTTPException(status_code=404, detail="core_runtime_not_registered")
        if str(record.management_mode or "").strip().lower() != "manage":
            raise HTTPException(status_code=409, detail="core_runtime_monitor_only")
        self._append_boot_log(
            "runtime_action",
            context={
                "runtime_id": runtime_id,
                "action": action,
                "scope": "core_runtime",
                "message": f"{action.capitalize()} {runtime_id}",
            },
        )
        units = self._extract_systemd_units(record.runtime_metadata)
        if units:
            ok, error = self._systemctl_action(units, action)
            if not ok:
                self._append_boot_log(
                    "runtime_action",
                    context={
                        "runtime_id": runtime_id,
                        "action": action,
                        "scope": "core_runtime",
                        "status": "systemd_failed",
                        "error": error,
                    },
                )
                raise HTTPException(status_code=502, detail="systemd_action_failed")
        updated = self._core_runtime_store.apply_action(
            runtime_id,
            action=action,
            desired_state=desired_state,
            lifecycle_state=lifecycle_state,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="core_runtime_not_registered")
        return SupervisorCoreRuntimeActionResult(action=action, runtime=self._core_runtime_summary(updated))

    def start_core_runtime(self, runtime_id: str) -> SupervisorCoreRuntimeActionResult:
        return self._core_runtime_action(
            runtime_id,
            action="start",
            desired_state="running",
            lifecycle_state="starting",
        )

    def stop_core_runtime(self, runtime_id: str) -> SupervisorCoreRuntimeActionResult:
        return self._core_runtime_action(
            runtime_id,
            action="stop",
            desired_state="stopped",
            lifecycle_state="stopping",
        )

    def restart_core_runtime(self, runtime_id: str) -> SupervisorCoreRuntimeActionResult:
        return self._core_runtime_action(
            runtime_id,
            action="restart",
            desired_state="running",
            lifecycle_state="restarting",
        )

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

    def boot_loop_status(self) -> dict[str, Any]:
        return dict(self._boot_loop_status)

    def _boot_step_timeout_s(self) -> float:
        raw = str(os.getenv("HEXE_SUPERVISOR_BOOT_STEP_TIMEOUT_S", "60")).strip()
        try:
            parsed = float(raw)
        except Exception:
            return 60.0
        return max(5.0, parsed)

    def _boot_poll_s(self) -> float:
        raw = str(os.getenv("HEXE_SUPERVISOR_BOOT_POLL_S", "2")).strip()
        try:
            parsed = float(raw)
        except Exception:
            return 2.0
        return max(0.5, parsed)

    def _systemctl_action(self, units: list[str], action: str) -> tuple[bool, str | None]:
        if not units:
            return False, "systemd_units_missing"
        if shutil.which("systemctl") is None:
            return False, "systemctl_not_found"
        try:
            result = subprocess.run(
                ["systemctl", "--user", action, *units],
                capture_output=True,
                text=True,
                timeout=8.0,
                check=False,
            )
        except Exception as exc:
            return False, str(exc)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            return False, detail or f"systemctl_exit_{result.returncode}"
        return True, None

    def _extract_systemd_units(self, runtime_metadata: dict[str, Any] | None) -> list[str]:
        if not runtime_metadata:
            return []
        unit = runtime_metadata.get("systemd_unit") or runtime_metadata.get("systemd_service")
        if isinstance(unit, str) and unit.strip():
            return [unit.strip()]
        units = runtime_metadata.get("systemd_units")
        if isinstance(units, list):
            return [str(item).strip() for item in units if isinstance(item, str) and item.strip()]
        return []

    def _core_runtime_ready(self, record: SupervisorCoreRuntimeRecord) -> bool:
        freshness = self._core_freshness_state(
            record.last_seen_at,
            health_status=record.health_status,
            runtime_state=record.runtime_state,
        )
        if freshness != "online":
            return False
        if str(record.health_status or "").strip().lower() in {"error", "unhealthy"}:
            return False
        return str(record.runtime_state or "").strip().lower() == "running"

    def _node_runtime_ready(self, record: SupervisorRuntimeNodeRecord) -> bool:
        freshness = self._freshness_state(
            record.last_seen_at,
            health_status=record.health_status,
            runtime_state=record.runtime_state,
        )
        if freshness != "online":
            return False
        if str(record.health_status or "").strip().lower() in {"error", "unhealthy"}:
            return False
        return str(record.runtime_state or "").strip().lower() == "running"

    def _wait_for_core_runtime(self, runtime_id: str, timeout_s: float) -> bool:
        start = time.monotonic()
        while time.monotonic() - start < timeout_s:
            record = self._core_runtime_store.get(runtime_id)
            if record and self._core_runtime_ready(record):
                return True
            time.sleep(self._boot_poll_s())
        return False

    def _wait_for_node_runtime(self, node_id: str, timeout_s: float) -> bool:
        start = time.monotonic()
        while time.monotonic() - start < timeout_s:
            record = self._runtime_nodes_store.get(node_id)
            if record and self._node_runtime_ready(record):
                return True
            time.sleep(self._boot_poll_s())
        return False

    def _dependency_ready(self, dependency: str) -> bool:
        dep = str(dependency or "").strip()
        if not dep:
            return True
        if dep.startswith("node_type:"):
            node_type = dep.split(":", 1)[1].strip()
            return any(
                self._node_runtime_ready(record)
                for record in self._runtime_nodes_store.list()
                if record.node_type == node_type
            )
        record = self._core_runtime_store.get(dep)
        if record is None:
            record = self._core_runtime_store.get(f"addon:{dep}")
        if record is not None:
            return self._core_runtime_ready(record)
        return any(
            self._node_runtime_ready(record)
            for record in self._runtime_nodes_store.list()
            if record.node_type == dep
        )

    def _wait_for_dependencies(self, dependencies: list[str], timeout_s: float) -> bool:
        if not dependencies:
            return True
        start = time.monotonic()
        while time.monotonic() - start < timeout_s:
            if all(self._dependency_ready(dep) for dep in dependencies):
                return True
            time.sleep(self._boot_poll_s())
        return False

    def run_boot_loop(self) -> dict[str, Any]:
        plan, warnings = load_boot_order_plan()
        results: dict[str, Any] = {
            "warnings": warnings,
            "core": [],
            "nodes": [],
        }
        started_at = self._now_iso()
        self._boot_loop_status = {
            "state": "running",
            "started_at": started_at,
            "updated_at": started_at,
            "warnings": list(warnings),
            "results": {},
        }
        self._append_boot_log("boot_loop_start", context={"started_at": started_at})
        timeout_s = self._boot_step_timeout_s()
        core_order = plan.get("core", {}).get("boot_order", {})
        core_deps = plan.get("core", {}).get("dependencies", {})
        for runtime_id, _ in sorted(core_order.items(), key=lambda item: (item[1], item[0])):
            deps = core_deps.get(runtime_id, [])
            if not self._wait_for_dependencies(deps, timeout_s):
                entry = {"runtime_id": runtime_id, "status": "dependency_timeout"}
                results["core"].append(entry)
                self._append_boot_log("boot_loop_step", context={**entry, "message": f"{runtime_id} dependency timeout"})
                continue
            record = self._core_runtime_store.get(runtime_id)
            if record is None:
                entry = {"runtime_id": runtime_id, "status": "missing"}
                results["core"].append(entry)
                self._append_boot_log("boot_loop_step", context={**entry, "message": f"{runtime_id} missing"})
                continue
            self._append_boot_log(
                "boot_loop_step",
                context={"runtime_id": runtime_id, "status": "starting", "message": f"Starting {runtime_id}"},
            )
            if str(record.management_mode or "").strip().lower() == "manage":
                units = self._extract_systemd_units(record.runtime_metadata)
                if units:
                    ok, error = self._systemctl_action(units, "start")
                    if not ok:
                        entry = {"runtime_id": runtime_id, "status": "start_failed", "error": error}
                        results["core"].append(entry)
                        self._append_boot_log(
                            "boot_loop_step",
                            context={**entry, "message": f"{runtime_id} start failed"},
                        )
                        continue
                self.start_core_runtime(runtime_id)
            ready = self._wait_for_core_runtime(runtime_id, timeout_s)
            entry = {"runtime_id": runtime_id, "status": "ready" if ready else "timeout"}
            results["core"].append(entry)
            if ready:
                self._append_boot_log(
                    "boot_loop_step",
                    context={**entry, "message": f"{runtime_id} healthy"},
                )
            else:
                self._append_boot_log(
                    "boot_loop_step",
                    context={**entry, "message": f"{runtime_id} health timeout"},
                )

        node_order = plan.get("nodes", {}).get("boot_order", {})
        node_deps = plan.get("nodes", {}).get("dependencies", {})
        for node_type, _ in sorted(node_order.items(), key=lambda item: (item[1], item[0])):
            deps = node_deps.get(node_type, [])
            if not self._wait_for_dependencies(deps, timeout_s):
                entry = {"node_type": node_type, "status": "dependency_timeout"}
                results["nodes"].append(entry)
                self._append_boot_log("boot_loop_step", context={**entry, "message": f"{node_type} dependency timeout"})
                continue
            runtimes = [item for item in self._runtime_nodes_store.list() if item.node_type == node_type]
            if not runtimes:
                entry = {"node_type": node_type, "status": "missing"}
                results["nodes"].append(entry)
                self._append_boot_log("boot_loop_step", context={**entry, "message": f"{node_type} missing"})
                continue
            for record in sorted(runtimes, key=lambda item: (item.node_name, item.node_id)):
                self._append_boot_log(
                    "boot_loop_step",
                    context={"node_type": node_type, "node_id": record.node_id, "status": "starting", "message": f"Starting {record.node_id}"},
                )
                self.start_registered_runtime(record.node_id)
                ready = self._wait_for_node_runtime(record.node_id, timeout_s)
                entry = {
                    "node_type": node_type,
                    "node_id": record.node_id,
                    "status": "ready" if ready else "timeout",
                }
                results["nodes"].append(entry)
                if ready:
                    self._append_boot_log(
                        "boot_loop_step",
                        context={**entry, "message": f"{record.node_id} healthy"},
                    )
                else:
                    self._append_boot_log(
                        "boot_loop_step",
                        context={**entry, "message": f"{record.node_id} health timeout"},
                    )
        finished_at = self._now_iso()
        self._boot_loop_status = {
            "state": "finished",
            "started_at": started_at,
            "finished_at": finished_at,
            "updated_at": finished_at,
            "warnings": list(warnings),
            "results": results,
        }
        self._append_boot_log("boot_loop_complete", context={"finished_at": finished_at})
        return results

    def list_managed_nodes(self) -> list[ManagedNodeSummary]:
        return self._managed_nodes()

    def admission_summary(
        self,
        *,
        total_capacity_units: int = 100,
        reserve_units: int = 5,
        headroom_pct: float = 0.05,
    ) -> SupervisorAdmissionContextSummary:
        resources = self._host_resources()
        managed_nodes = self._managed_nodes()
        healthy_count = sum(1 for item in managed_nodes if str(item.health_status or "").strip().lower() == "healthy")

        busy = 0
        if resources.cpu_percent_total >= 95 or resources.memory_percent >= 95:
            busy = 10
        elif resources.cpu_percent_total >= 85 or resources.memory_percent >= 85:
            busy = 8
        elif resources.cpu_percent_total >= 70 or resources.memory_percent >= 70:
            busy = 6
        elif resources.cpu_percent_total >= 50 or resources.memory_percent >= 50:
            busy = 3

        busy_to_percent = {
            0: 1.00,
            1: 1.00,
            2: 1.00,
            3: 0.80,
            4: 0.65,
            5: 0.50,
            6: 0.35,
            7: 0.25,
            8: 0.15,
            9: 0.10,
            10: 0.00,
        }
        usable = int((total_capacity_units * busy_to_percent[busy]) * max(0.0, 1.0 - headroom_pct)) - reserve_units
        available_capacity = max(0, usable)
        host_ready = available_capacity > 0 and resources.memory_available_bytes > 0

        return SupervisorAdmissionContextSummary(
            admission_state="ready" if host_ready else "degraded",
            execution_host_ready=host_ready,
            unavailable_reason=None if host_ready else "host_capacity_unavailable",
            host_busy_rating=busy,
            total_capacity_units=max(0, int(total_capacity_units)),
            available_capacity_units=available_capacity,
            managed_node_count=len(managed_nodes),
            healthy_managed_node_count=healthy_count,
        )

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

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _boot_log_path(self) -> Path:
        raw = str(os.getenv("HEXE_SUPERVISOR_BOOT_LOG", "var/supervisor/boot.log")).strip()
        return Path(raw or "var/supervisor/boot.log")

    def _append_boot_log(self, event: str, *, context: dict[str, Any] | None = None) -> None:
        log_path = self._boot_log_path()
        payload: dict[str, Any] = {"event": str(event)}
        if context:
            payload.update(context)
        message = str(payload.get("message") or event).strip()
        omit_keys = {"message"}
        if message == event:
            omit_keys.add("event")
        details = []
        for key in sorted(k for k in payload.keys() if k not in omit_keys):
            details.append(f"{key}={payload.get(key)}")
        suffix = f" | {' '.join(details)}" if details else ""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{ts} [{event}] {message}{suffix}\n")
        except Exception:
            return

    def _set_desired_state(self, snapshot, desired_state: str) -> None:
        if not isinstance(snapshot.raw_desired, dict):
            return
        payload = dict(snapshot.raw_desired)
        payload["desired_state"] = desired_state
        self._write_json(Path(snapshot.desired_path), payload)

    def _set_runtime_state(
        self,
        snapshot,
        runtime_state: str,
        *,
        lifecycle_state: str,
        last_action: str,
        error: str | None = None,
    ) -> None:
        payload = dict(snapshot.raw_runtime) if isinstance(snapshot.raw_runtime, dict) else {}
        payload["state"] = runtime_state
        payload["lifecycle_state"] = lifecycle_state
        payload["last_action"] = last_action
        payload["last_action_at"] = self._now_iso()
        if error:
            payload["error"] = error
            payload["last_error"] = error
        else:
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
        self._append_boot_log(
            "runtime_action",
            context={"runtime_id": node_id, "action": "start", "scope": "managed_node"},
        )
        self._set_desired_state(snapshot, "running")
        self._set_runtime_state(snapshot, "running", lifecycle_state="starting", last_action="start")
        try:
            compose_up(compose_files, project_name)
        except Exception as exc:
            self._set_runtime_state(snapshot, "error", lifecycle_state="error", last_action="start", error=str(exc))
            raise
        self._set_runtime_state(snapshot, "running", lifecycle_state="running", last_action="start")
        return self._action_result("start", node_id)

    def stop_managed_node(self, node_id: str) -> SupervisorNodeActionResult:
        snapshot = self._runtime_snapshot(node_id)
        compose_files = self._compose_files_for_snapshot(snapshot)
        project_name = self._project_name_for_snapshot(snapshot)
        self._append_boot_log(
            "runtime_action",
            context={"runtime_id": node_id, "action": "stop", "scope": "managed_node"},
        )
        self._set_desired_state(snapshot, "stopped")
        self._set_runtime_state(snapshot, "running", lifecycle_state="stopping", last_action="stop")
        try:
            compose_down(compose_files, project_name)
        except Exception as exc:
            self._set_runtime_state(snapshot, "error", lifecycle_state="error", last_action="stop", error=str(exc))
            raise
        self._set_runtime_state(snapshot, "stopped", lifecycle_state="stopped", last_action="stop")
        return self._action_result("stop", node_id)

    def restart_managed_node(self, node_id: str) -> SupervisorNodeActionResult:
        snapshot = self._runtime_snapshot(node_id)
        compose_files = self._compose_files_for_snapshot(snapshot)
        project_name = self._project_name_for_snapshot(snapshot)
        self._append_boot_log(
            "runtime_action",
            context={"runtime_id": node_id, "action": "restart", "scope": "managed_node"},
        )
        self._set_desired_state(snapshot, "running")
        self._set_runtime_state(snapshot, "running", lifecycle_state="restarting", last_action="restart")
        try:
            compose_down(compose_files, project_name)
            compose_up(compose_files, project_name)
        except Exception as exc:
            self._set_runtime_state(snapshot, "error", lifecycle_state="error", last_action="restart", error=str(exc))
            raise
        self._set_runtime_state(snapshot, "running", lifecycle_state="running", last_action="restart")
        return self._action_result("restart", node_id)

    def _cloudflared_runtime_root(self) -> Path:
        return Path(os.getenv("SYNTHIA_EDGE_RUNTIME_DIR", Path(os.getcwd()) / "var" / "edge" / "cloudflared"))

    def _cloudflared_provider(self) -> str:
        provider = str(os.getenv("SYNTHIA_CLOUDFLARED_PROVIDER", "auto")).strip().lower() or "auto"
        if provider in {"disabled", "docker", "binary"}:
            return provider
        return "auto"

    def _cloudflared_container_name(self) -> str:
        return str(os.getenv("SYNTHIA_CLOUDFLARED_CONTAINER_NAME", "hexe-cloudflared")).strip() or "hexe-cloudflared"

    def _cloudflared_image(self) -> str:
        return str(os.getenv("SYNTHIA_CLOUDFLARED_IMAGE", "cloudflare/cloudflared:latest")).strip() or "cloudflare/cloudflared:latest"

    def _cloudflared_restart_policy(self) -> str:
        policy = str(os.getenv("SYNTHIA_CLOUDFLARED_RESTART_POLICY", "unless-stopped")).strip().lower()
        return policy if policy in {"no", "on-failure", "always", "unless-stopped"} else "unless-stopped"

    def _cloudflared_log_path(self) -> Path:
        return self._cloudflared_runtime_root() / "cloudflared.log"

    def _cloudflared_pid_path(self) -> Path:
        return self._cloudflared_runtime_root() / "cloudflared.pid"

    def _docker_available(self) -> bool:
        return shutil.which("docker") is not None

    def _cloudflared_binary_available(self) -> bool:
        return shutil.which("cloudflared") is not None

    def _write_runtime_payload(self, payload: dict[str, Any]) -> None:
        runtime_path = self._cloudflared_runtime_root() / "runtime.json"
        self._write_json(runtime_path, payload)

    def _read_runtime_payload(self) -> dict[str, Any]:
        runtime_path = self._cloudflared_runtime_root() / "runtime.json"
        if not runtime_path.exists():
            return {}
        try:
            raw = json.loads(runtime_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}

    def _docker_cmd(self, args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)

    def _cloudflared_container_exists(self) -> bool:
        if not self._docker_available():
            return False
        result = self._docker_cmd(["ps", "-a", "--filter", f"name=^{self._cloudflared_container_name()}$", "--format", "{{.Names}}"])
        if result.returncode != 0:
            return False
        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return self._cloudflared_container_name() in names

    def _cloudflared_container_running(self) -> bool:
        if not self._docker_available():
            return False
        result = self._docker_cmd(["inspect", "-f", "{{.State.Running}}", self._cloudflared_container_name()])
        return result.returncode == 0 and str(result.stdout or "").strip().lower() == "true"

    def _remove_cloudflared_container(self) -> None:
        if self._cloudflared_container_exists():
            self._docker_cmd(["rm", "-f", self._cloudflared_container_name()])

    def _stop_cloudflared_native(self) -> None:
        pid_path = self._cloudflared_pid_path()
        if not pid_path.exists():
            return
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except Exception:
            pid_path.unlink(missing_ok=True)
            return
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
        except Exception:
            pass
        pid_path.unlink(missing_ok=True)

    def _ensure_cloudflared_stopped(self) -> None:
        self._remove_cloudflared_container()
        self._stop_cloudflared_native()

    def _cloudflared_runtime_status(self) -> dict[str, Any]:
        root = self._cloudflared_runtime_root()
        runtime_path = root / "runtime.json"
        payload = self._read_runtime_payload()
        if not runtime_path.exists():
            return {"exists": False}
        provider = str(payload.get("provider") or self._cloudflared_provider() or "unknown")
        if provider == "docker":
            if not self._docker_available():
                payload.update({"state": "error", "healthy": False, "last_error": "docker_binary_not_found"})
            elif self._cloudflared_container_running():
                payload.update({"state": "running", "healthy": True, "last_error": None})
            elif self._cloudflared_container_exists():
                inspect = self._docker_cmd(["inspect", "-f", "{{.State.Status}}", self._cloudflared_container_name()])
                payload.update(
                    {
                        "state": str(inspect.stdout or "").strip().lower() or "stopped",
                        "healthy": False,
                        "last_error": str(payload.get("last_error") or "cloudflared_container_not_running"),
                    }
                )
            else:
                payload.update({"state": "stopped", "healthy": False, "last_error": str(payload.get("last_error") or "runtime_not_started")})
        elif provider == "binary":
            pid_path = self._cloudflared_pid_path()
            try:
                pid = int(pid_path.read_text(encoding="utf-8").strip()) if pid_path.exists() else 0
            except Exception:
                pid = 0
            running = False
            if pid > 0:
                try:
                    os.kill(pid, 0)
                    running = True
                except Exception:
                    running = False
            payload.update(
                {
                    "state": "running" if running else "stopped",
                    "healthy": running,
                    "last_error": None if running else str(payload.get("last_error") or "runtime_not_started"),
                }
            )
        payload["exists"] = True
        payload["checked_at"] = self._now_iso()
        self._write_runtime_payload(payload)
        return payload

    def apply_cloudflared_config(self, config: dict[str, Any]) -> dict[str, Any]:
        root = self._cloudflared_runtime_root()
        root.mkdir(parents=True, exist_ok=True)
        config_path = root / "config.json"
        config_payload = dict(config)
        config_payload.pop("tunnel-token", None)
        self._write_json(config_path, config_payload)
        desired_enabled = bool(config.get("desired_enabled"))
        tunnel_id = str(config.get("tunnel") or "").strip()
        tunnel_token = str(config.get("tunnel-token") or "").strip()
        provider = self._cloudflared_provider()
        if provider == "auto":
            if self._docker_available():
                provider = "docker"
            elif self._cloudflared_binary_available():
                provider = "binary"
            else:
                provider = "disabled"

        runtime_payload = {
            "runtime_id": "cloudflared",
            "provider": provider,
            "state": "configured",
            "healthy": False,
            "last_action": "reconcile",
            "last_action_at": self._now_iso(),
            "config_path": str(config_path),
            "tunnel_id": tunnel_id or None,
            "container_name": self._cloudflared_container_name() if provider == "docker" else None,
        }

        if not desired_enabled:
            self._ensure_cloudflared_stopped()
            runtime_payload.update({"state": "stopped", "healthy": False, "last_error": None})
            self._write_runtime_payload(runtime_payload)
            return {"ok": True, "runtime_state": "stopped", "config_path": str(config_path)}

        if not tunnel_id:
            runtime_payload.update({"state": "error", "last_error": "cloudflare_tunnel_missing"})
            self._write_runtime_payload(runtime_payload)
            return {"ok": False, "runtime_state": "error", "config_path": str(config_path), "error": "cloudflare_tunnel_missing"}
        if provider == "disabled":
            runtime_payload.update({"state": "configured", "healthy": False, "last_error": "cloudflared_runtime_disabled"})
            self._write_runtime_payload(runtime_payload)
            return {"ok": False, "runtime_state": "configured", "config_path": str(config_path), "error": "cloudflared_runtime_disabled"}
        if not tunnel_token:
            runtime_payload.update({"state": "error", "last_error": "cloudflare_tunnel_token_missing"})
            self._write_runtime_payload(runtime_payload)
            return {"ok": False, "runtime_state": "error", "config_path": str(config_path), "error": "cloudflare_tunnel_token_missing"}

        try:
            self._ensure_cloudflared_stopped()
            if provider == "docker":
                if not self._docker_available():
                    raise RuntimeError("docker_binary_not_found")
                result = self._docker_cmd(
                    [
                        "run",
                        "-d",
                        "--name",
                        self._cloudflared_container_name(),
                        "--network",
                        "host",
                        "--restart",
                        self._cloudflared_restart_policy(),
                        "-e",
                        f"TUNNEL_TOKEN={tunnel_token}",
                        self._cloudflared_image(),
                        "tunnel",
                        "--no-autoupdate",
                        "run",
                    ]
                )
                if result.returncode != 0:
                    raise RuntimeError(str(result.stderr or result.stdout or "cloudflared_docker_run_failed").strip())
                runtime_payload.update(
                    {
                        "state": "running",
                        "healthy": True,
                        "last_error": None,
                        "last_started_at": self._now_iso(),
                        "container_id": str(result.stdout or "").strip() or None,
                    }
                )
            else:
                if not self._cloudflared_binary_available():
                    raise RuntimeError("cloudflared_binary_not_found")
                log_path = self._cloudflared_log_path()
                log_path.touch(mode=0o600, exist_ok=True)
                with log_path.open("ab") as handle:
                    proc = subprocess.Popen(
                        ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token", tunnel_token],
                        stdout=handle,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                self._cloudflared_pid_path().write_text(f"{proc.pid}\n", encoding="utf-8")
                runtime_payload.update(
                    {
                        "state": "running",
                        "healthy": True,
                        "last_error": None,
                        "last_started_at": self._now_iso(),
                        "pid": proc.pid,
                    }
                )
        except Exception as exc:
            runtime_payload.update({"state": "error", "healthy": False, "last_error": str(exc) or type(exc).__name__})
            self._write_runtime_payload(runtime_payload)
            return {"ok": False, "runtime_state": runtime_payload["state"], "config_path": str(config_path), "error": runtime_payload["last_error"]}

        self._write_runtime_payload(runtime_payload)
        return {"ok": True, "runtime_state": str(runtime_payload["state"]), "config_path": str(config_path)}

    def get_runtime_state(self, runtime_id: str) -> dict[str, Any]:
        if runtime_id != "cloudflared":
            return {"exists": False}
        return self._cloudflared_runtime_status()

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
                    "host-local worker/process execution helpers",
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

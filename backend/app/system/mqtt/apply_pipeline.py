from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass

from .authority_audit import MqttAuthorityAuditStore
from .runtime_boundary import BrokerRuntimeBoundary, BrokerRuntimeStatus


@dataclass(frozen=True)
class ApplyPipelineResult:
    ok: bool
    status: str
    runtime: BrokerRuntimeStatus
    live_dir: str
    rolled_back: bool
    error: str | None = None


class MqttApplyPipeline:
    def __init__(
        self,
        *,
        runtime_boundary: BrokerRuntimeBoundary,
        audit_store: MqttAuthorityAuditStore,
        live_dir: str,
    ) -> None:
        self._runtime = runtime_boundary
        self._audit = audit_store
        self._live_dir = live_dir
        os.makedirs(self._live_dir, exist_ok=True)

    async def apply(self, artifacts: dict[str, str]) -> ApplyPipelineResult:
        error = self._validate_artifacts(artifacts)
        if error:
            runtime = await self._runtime.get_status()
            await self._audit.append_event(
                event_type="mqtt_apply",
                status="failed_validation",
                message=error,
                payload={"artifacts": sorted(artifacts.keys())},
            )
            return ApplyPipelineResult(False, "failed_validation", runtime, self._live_dir, False, error=error)

        staged_dir = tempfile.mkdtemp(prefix="mqtt-stage-")
        backup_dir = tempfile.mkdtemp(prefix="mqtt-backup-")
        rolled_back = False
        try:
            self._write_artifacts(staged_dir, artifacts)
            self._backup_live_dir(backup_dir)
            self._promote_staged(staged_dir)
            runtime = await self._runtime.reload()
            if not runtime.healthy:
                runtime = await self._runtime.controlled_restart()
            if not runtime.healthy:
                rolled_back = True
                self._restore_backup(backup_dir)
                runtime = await self._runtime.reload()
                await self._audit.append_event(
                    event_type="mqtt_apply",
                    status="rolled_back",
                    message="runtime_unhealthy_after_apply",
                    payload={"live_dir": self._live_dir},
                )
                return ApplyPipelineResult(False, "rolled_back", runtime, self._live_dir, True, error="runtime_unhealthy_after_apply")

            await self._audit.append_event(
                event_type="mqtt_apply",
                status="applied",
                message=None,
                payload={"live_dir": self._live_dir, "files": sorted(artifacts.keys())},
            )
            return ApplyPipelineResult(True, "applied", runtime, self._live_dir, rolled_back)
        finally:
            shutil.rmtree(staged_dir, ignore_errors=True)
            shutil.rmtree(backup_dir, ignore_errors=True)

    @staticmethod
    def _validate_artifacts(artifacts: dict[str, str]) -> str | None:
        if not artifacts:
            return "no_artifacts_provided"
        for name, value in artifacts.items():
            clean_name = str(name).strip()
            if not clean_name or "/" in clean_name or ".." in clean_name:
                return f"invalid_artifact_name:{name}"
            if value is None:
                return f"artifact_content_missing:{name}"
            if not str(value).strip():
                return f"artifact_content_empty:{name}"
        return None

    @staticmethod
    def _write_artifacts(staged_dir: str, artifacts: dict[str, str]) -> None:
        for name, value in sorted(artifacts.items(), key=lambda item: item[0]):
            with open(os.path.join(staged_dir, name), "w", encoding="utf-8") as handle:
                handle.write(str(value))

    def _backup_live_dir(self, backup_dir: str) -> None:
        if not os.path.exists(self._live_dir):
            return
        for name in os.listdir(self._live_dir):
            src = os.path.join(self._live_dir, name)
            dst = os.path.join(backup_dir, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

    def _restore_backup(self, backup_dir: str) -> None:
        for name in os.listdir(self._live_dir):
            path = os.path.join(self._live_dir, name)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
        for name in os.listdir(backup_dir):
            src = os.path.join(backup_dir, name)
            dst = os.path.join(self._live_dir, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

    def _promote_staged(self, staged_dir: str) -> None:
        for name in os.listdir(self._live_dir):
            path = os.path.join(self._live_dir, name)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
        for name in sorted(os.listdir(staged_dir)):
            src = os.path.join(staged_dir, name)
            dst = os.path.join(self._live_dir, name)
            shutil.copy2(src, dst)

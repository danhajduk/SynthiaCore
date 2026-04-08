from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUPERVISOR_CORE_RUNTIME_SCHEMA_VERSION = "1"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass
class SupervisorCoreRuntimeRecord:
    runtime_id: str
    runtime_name: str
    runtime_kind: str
    management_mode: str
    desired_state: str
    runtime_state: str
    lifecycle_state: str
    health_status: str
    registered_at: str
    updated_at: str
    host_id: str | None = None
    hostname: str | None = None
    freshness_state: str = "online"
    last_seen_at: str | None = None
    last_action: str | None = None
    last_action_at: str | None = None
    last_error: str | None = None
    running: bool | None = None
    runtime_metadata: dict[str, object] = field(default_factory=dict)
    resource_usage: dict[str, object] = field(default_factory=dict)
    schema_version: str = SUPERVISOR_CORE_RUNTIME_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SupervisorCoreRuntimeStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (_repo_root() / "data" / "supervisor_core_runtimes.json")
        self._records_by_id: dict[str, SupervisorCoreRuntimeRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return

        if isinstance(raw, dict):
            items = raw.get("items") if isinstance(raw.get("items"), list) else []
        elif isinstance(raw, list):
            items = raw
        else:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            runtime_id = str(item.get("runtime_id") or "").strip()
            runtime_name = str(item.get("runtime_name") or "").strip()
            runtime_kind = str(item.get("runtime_kind") or "").strip() or "core_service"
            management_mode = str(item.get("management_mode") or "").strip() or "monitor"
            desired_state = str(item.get("desired_state") or "").strip() or "running"
            runtime_state = str(item.get("runtime_state") or "").strip() or "unknown"
            lifecycle_state = str(item.get("lifecycle_state") or "").strip() or "unknown"
            health_status = str(item.get("health_status") or "").strip() or "unknown"
            registered_at = str(item.get("registered_at") or "").strip() or _utcnow_iso()
            updated_at = str(item.get("updated_at") or "").strip() or registered_at
            if not (runtime_id and runtime_name):
                continue
            self._records_by_id[runtime_id] = SupervisorCoreRuntimeRecord(
                runtime_id=runtime_id,
                runtime_name=runtime_name,
                runtime_kind=runtime_kind,
                management_mode=management_mode,
                desired_state=desired_state,
                runtime_state=runtime_state,
                lifecycle_state=lifecycle_state,
                health_status=health_status,
                registered_at=registered_at,
                updated_at=updated_at,
                host_id=str(item.get("host_id") or "").strip() or None,
                hostname=str(item.get("hostname") or "").strip() or None,
                freshness_state=str(item.get("freshness_state") or "online").strip() or "online",
                last_seen_at=str(item.get("last_seen_at") or "").strip() or None,
                last_action=str(item.get("last_action") or "").strip() or None,
                last_action_at=str(item.get("last_action_at") or "").strip() or None,
                last_error=str(item.get("last_error") or "").strip() or None,
                running=item.get("running") if isinstance(item.get("running"), bool) else None,
                runtime_metadata=dict(item.get("runtime_metadata") or {}) if isinstance(item.get("runtime_metadata"), dict) else {},
                resource_usage=dict(item.get("resource_usage") or {}) if isinstance(item.get("resource_usage"), dict) else {},
                schema_version=str(item.get("schema_version") or SUPERVISOR_CORE_RUNTIME_SCHEMA_VERSION),
            )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SUPERVISOR_CORE_RUNTIME_SCHEMA_VERSION,
            "items": [item.to_dict() for item in sorted(self._records_by_id.values(), key=lambda x: x.runtime_id)],
        }
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def list(self) -> list[SupervisorCoreRuntimeRecord]:
        return sorted(self._records_by_id.values(), key=lambda item: item.runtime_id)

    def get(self, runtime_id: str) -> SupervisorCoreRuntimeRecord | None:
        return self._records_by_id.get(str(runtime_id or "").strip())

    def replace_all(self, records: list[SupervisorCoreRuntimeRecord]) -> None:
        self._records_by_id = {record.runtime_id: record for record in records if record.runtime_id}
        self._save()

    def upsert(self, record: SupervisorCoreRuntimeRecord) -> SupervisorCoreRuntimeRecord:
        now = _utcnow_iso()
        existing = self._records_by_id.get(record.runtime_id)
        if existing is not None:
            record.registered_at = existing.registered_at
            record.updated_at = now
        else:
            record.registered_at = record.registered_at or now
            record.updated_at = now
        self._records_by_id[record.runtime_id] = record
        self._save()
        return record

    def upsert_registration(self, *, payload: dict[str, Any]) -> SupervisorCoreRuntimeRecord:
        now = _utcnow_iso()
        runtime_id = str(payload.get("runtime_id") or "").strip()
        existing = self._records_by_id.get(runtime_id)
        record = SupervisorCoreRuntimeRecord(
            runtime_id=runtime_id,
            runtime_name=str(payload.get("runtime_name") or getattr(existing, "runtime_name", "") or "").strip(),
            runtime_kind=str(payload.get("runtime_kind") or getattr(existing, "runtime_kind", "core_service") or "core_service").strip()
            or "core_service",
            management_mode=str(payload.get("management_mode") or getattr(existing, "management_mode", "monitor") or "monitor").strip()
            or "monitor",
            desired_state=str(payload.get("desired_state") or getattr(existing, "desired_state", "running") or "running").strip() or "running",
            runtime_state=str(payload.get("runtime_state") or getattr(existing, "runtime_state", "running") or "running").strip() or "running",
            lifecycle_state=str(payload.get("lifecycle_state") or getattr(existing, "lifecycle_state", "running") or "running").strip() or "running",
            health_status=str(payload.get("health_status") or getattr(existing, "health_status", "unknown") or "unknown").strip() or "unknown",
            registered_at=getattr(existing, "registered_at", now),
            updated_at=now,
            host_id=str(payload.get("host_id") or getattr(existing, "host_id", "") or "").strip() or None,
            hostname=str(payload.get("hostname") or getattr(existing, "hostname", "") or "").strip() or None,
            freshness_state="online",
            last_seen_at=now,
            last_action=getattr(existing, "last_action", None),
            last_action_at=getattr(existing, "last_action_at", None),
            last_error=str(payload.get("last_error") or getattr(existing, "last_error", "") or "").strip() or None,
            running=payload.get("running") if isinstance(payload.get("running"), bool) else getattr(existing, "running", True),
            runtime_metadata=dict(payload.get("runtime_metadata") or getattr(existing, "runtime_metadata", {}) or {}),
            resource_usage=dict(payload.get("resource_usage") or getattr(existing, "resource_usage", {}) or {}),
        )
        return self.upsert(record)

    def apply_heartbeat(self, runtime_id: str, *, payload: dict[str, Any]) -> SupervisorCoreRuntimeRecord | None:
        existing = self.get(runtime_id)
        if existing is None:
            return None
        now = _utcnow_iso()
        record = SupervisorCoreRuntimeRecord(
            runtime_id=existing.runtime_id,
            runtime_name=existing.runtime_name,
            runtime_kind=existing.runtime_kind,
            management_mode=existing.management_mode,
            desired_state=existing.desired_state,
            runtime_state=str(payload.get("runtime_state") or existing.runtime_state or "unknown").strip() or "unknown",
            lifecycle_state=str(payload.get("lifecycle_state") or existing.lifecycle_state or "unknown").strip() or "unknown",
            health_status=str(payload.get("health_status") or existing.health_status or "unknown").strip() or "unknown",
            registered_at=existing.registered_at,
            updated_at=now,
            host_id=str(payload.get("host_id") or existing.host_id or "").strip() or None,
            hostname=str(payload.get("hostname") or existing.hostname or "").strip() or None,
            freshness_state="online",
            last_seen_at=now,
            last_action=existing.last_action,
            last_action_at=existing.last_action_at,
            last_error=str(payload.get("last_error") or existing.last_error or "").strip() or None,
            running=payload.get("running") if isinstance(payload.get("running"), bool) else existing.running,
            runtime_metadata=dict(payload.get("runtime_metadata") or existing.runtime_metadata or {}),
            resource_usage=dict(payload.get("resource_usage") or existing.resource_usage or {}),
        )
        return self.upsert(record)

    def apply_action(
        self,
        runtime_id: str,
        *,
        action: str,
        desired_state: str,
        lifecycle_state: str,
    ) -> SupervisorCoreRuntimeRecord | None:
        existing = self.get(runtime_id)
        if existing is None:
            return None
        now = _utcnow_iso()
        record = SupervisorCoreRuntimeRecord(
            runtime_id=existing.runtime_id,
            runtime_name=existing.runtime_name,
            runtime_kind=existing.runtime_kind,
            management_mode=existing.management_mode,
            desired_state=desired_state,
            runtime_state=existing.runtime_state,
            lifecycle_state=lifecycle_state,
            health_status=existing.health_status,
            registered_at=existing.registered_at,
            updated_at=now,
            host_id=existing.host_id,
            hostname=existing.hostname,
            freshness_state=existing.freshness_state,
            last_seen_at=existing.last_seen_at,
            last_action=action,
            last_action_at=now,
            last_error=existing.last_error,
            running=existing.running,
            runtime_metadata=dict(existing.runtime_metadata or {}),
            resource_usage=dict(existing.resource_usage or {}),
        )
        return self.upsert(record)

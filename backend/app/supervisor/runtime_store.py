from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUPERVISOR_RUNTIME_NODE_SCHEMA_VERSION = "1"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass
class SupervisorRuntimeNodeRecord:
    node_id: str
    node_name: str
    node_type: str
    desired_state: str
    runtime_state: str
    lifecycle_state: str
    health_status: str
    registered_at: str
    updated_at: str
    host_id: str | None = None
    hostname: str | None = None
    api_base_url: str | None = None
    ui_base_url: str | None = None
    health_detail: str | None = None
    freshness_state: str = "online"
    last_seen_at: str | None = None
    last_action: str | None = None
    last_action_at: str | None = None
    last_error: str | None = None
    running: bool | None = None
    runtime_metadata: dict[str, object] = field(default_factory=dict)
    resource_usage: dict[str, object] = field(default_factory=dict)
    schema_version: str = SUPERVISOR_RUNTIME_NODE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SupervisorRuntimeNodesStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (_repo_root() / "data" / "supervisor_runtime_nodes.json")
        self._records_by_node: dict[str, SupervisorRuntimeNodeRecord] = {}
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
            node_id = str(item.get("node_id") or "").strip()
            node_name = str(item.get("node_name") or "").strip()
            node_type = str(item.get("node_type") or "").strip()
            desired_state = str(item.get("desired_state") or "").strip() or "running"
            runtime_state = str(item.get("runtime_state") or "").strip() or "unknown"
            lifecycle_state = str(item.get("lifecycle_state") or "").strip() or "unknown"
            health_status = str(item.get("health_status") or "").strip() or "unknown"
            registered_at = str(item.get("registered_at") or "").strip() or _utcnow_iso()
            updated_at = str(item.get("updated_at") or "").strip() or registered_at
            if not (node_id and node_name and node_type):
                continue
            self._records_by_node[node_id] = SupervisorRuntimeNodeRecord(
                node_id=node_id,
                node_name=node_name,
                node_type=node_type,
                desired_state=desired_state,
                runtime_state=runtime_state,
                lifecycle_state=lifecycle_state,
                health_status=health_status,
                registered_at=registered_at,
                updated_at=updated_at,
                host_id=str(item.get("host_id") or "").strip() or None,
                hostname=str(item.get("hostname") or "").strip() or None,
                api_base_url=str(item.get("api_base_url") or "").strip() or None,
                ui_base_url=str(item.get("ui_base_url") or "").strip() or None,
                health_detail=str(item.get("health_detail") or "").strip() or None,
                freshness_state=str(item.get("freshness_state") or "online").strip() or "online",
                last_seen_at=str(item.get("last_seen_at") or "").strip() or None,
                last_action=str(item.get("last_action") or "").strip() or None,
                last_action_at=str(item.get("last_action_at") or "").strip() or None,
                last_error=str(item.get("last_error") or "").strip() or None,
                running=item.get("running") if isinstance(item.get("running"), bool) else None,
                runtime_metadata=dict(item.get("runtime_metadata") or {}) if isinstance(item.get("runtime_metadata"), dict) else {},
                resource_usage=dict(item.get("resource_usage") or {}) if isinstance(item.get("resource_usage"), dict) else {},
                schema_version=str(item.get("schema_version") or SUPERVISOR_RUNTIME_NODE_SCHEMA_VERSION),
            )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SUPERVISOR_RUNTIME_NODE_SCHEMA_VERSION,
            "items": [item.to_dict() for item in sorted(self._records_by_node.values(), key=lambda x: x.node_id)],
        }
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def list(self) -> list[SupervisorRuntimeNodeRecord]:
        return sorted(self._records_by_node.values(), key=lambda item: item.node_id)

    def get(self, node_id: str) -> SupervisorRuntimeNodeRecord | None:
        return self._records_by_node.get(str(node_id or "").strip())

    def upsert(self, record: SupervisorRuntimeNodeRecord) -> SupervisorRuntimeNodeRecord:
        now = _utcnow_iso()
        existing = self._records_by_node.get(record.node_id)
        if existing is not None:
            record.registered_at = existing.registered_at
            record.updated_at = now
        else:
            record.registered_at = record.registered_at or now
            record.updated_at = now
        self._records_by_node[record.node_id] = record
        self._save()
        return record

    def upsert_registration(self, *, payload: dict[str, Any]) -> SupervisorRuntimeNodeRecord:
        now = _utcnow_iso()
        node_id = str(payload.get("node_id") or "").strip()
        existing = self._records_by_node.get(node_id)
        record = SupervisorRuntimeNodeRecord(
            node_id=node_id,
            node_name=str(payload.get("node_name") or getattr(existing, "node_name", "") or "").strip(),
            node_type=str(payload.get("node_type") or getattr(existing, "node_type", "") or "").strip(),
            desired_state=str(payload.get("desired_state") or getattr(existing, "desired_state", "running") or "running").strip() or "running",
            runtime_state=str(payload.get("runtime_state") or getattr(existing, "runtime_state", "running") or "running").strip() or "running",
            lifecycle_state=str(payload.get("lifecycle_state") or getattr(existing, "lifecycle_state", "running") or "running").strip() or "running",
            health_status=str(payload.get("health_status") or getattr(existing, "health_status", "unknown") or "unknown").strip() or "unknown",
            registered_at=getattr(existing, "registered_at", now),
            updated_at=now,
            host_id=str(payload.get("host_id") or getattr(existing, "host_id", "") or "").strip() or None,
            hostname=str(payload.get("hostname") or getattr(existing, "hostname", "") or "").strip() or None,
            api_base_url=str(payload.get("api_base_url") or getattr(existing, "api_base_url", "") or "").strip() or None,
            ui_base_url=str(payload.get("ui_base_url") or getattr(existing, "ui_base_url", "") or "").strip() or None,
            health_detail=str(payload.get("health_detail") or getattr(existing, "health_detail", "") or "").strip() or None,
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

    def apply_heartbeat(self, node_id: str, *, payload: dict[str, Any]) -> SupervisorRuntimeNodeRecord | None:
        existing = self.get(node_id)
        if existing is None:
            return None
        now = _utcnow_iso()
        record = SupervisorRuntimeNodeRecord(
            node_id=existing.node_id,
            node_name=existing.node_name,
            node_type=existing.node_type,
            desired_state=existing.desired_state,
            runtime_state=str(payload.get("runtime_state") or existing.runtime_state or "unknown").strip() or "unknown",
            lifecycle_state=str(payload.get("lifecycle_state") or existing.lifecycle_state or "unknown").strip() or "unknown",
            health_status=str(payload.get("health_status") or existing.health_status or "unknown").strip() or "unknown",
            registered_at=existing.registered_at,
            updated_at=now,
            host_id=str(payload.get("host_id") or existing.host_id or "").strip() or None,
            hostname=str(payload.get("hostname") or existing.hostname or "").strip() or None,
            api_base_url=str(payload.get("api_base_url") or existing.api_base_url or "").strip() or None,
            ui_base_url=str(payload.get("ui_base_url") or existing.ui_base_url or "").strip() or None,
            health_detail=str(payload.get("health_detail") or existing.health_detail or "").strip() or None,
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
        node_id: str,
        *,
        action: str,
        desired_state: str,
        lifecycle_state: str,
    ) -> SupervisorRuntimeNodeRecord | None:
        existing = self.get(node_id)
        if existing is None:
            return None
        now = _utcnow_iso()
        record = SupervisorRuntimeNodeRecord(
            node_id=existing.node_id,
            node_name=existing.node_name,
            node_type=existing.node_type,
            desired_state=desired_state,
            runtime_state=existing.runtime_state,
            lifecycle_state=lifecycle_state,
            health_status=existing.health_status,
            registered_at=existing.registered_at,
            updated_at=now,
            host_id=existing.host_id,
            hostname=existing.hostname,
            api_base_url=existing.api_base_url,
            ui_base_url=existing.ui_base_url,
            health_detail=existing.health_detail,
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

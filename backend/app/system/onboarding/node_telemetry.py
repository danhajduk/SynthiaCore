from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NODE_TELEMETRY_SCHEMA_VERSION = "1"
ALLOWED_NODE_TELEMETRY_EVENTS = {
    "lifecycle_transition",
    "degraded_state",
    "capability_declaration_success",
    "governance_sync",
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    # backend/app/system/onboarding/node_telemetry.py -> onboarding(0), system(1), app(2), backend(3), repo(4)
    return Path(__file__).resolve().parents[4]


@dataclass
class NodeTelemetryRecord:
    node_id: str
    event_type: str
    event_state: str | None
    message: str | None
    payload: dict[str, Any]
    received_at: str
    schema_version: str = NODE_TELEMETRY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "node_id": self.node_id,
            "event_type": self.event_type,
            "event_state": self.event_state,
            "message": self.message,
            "payload": copy.deepcopy(self.payload),
            "received_at": self.received_at,
        }


class NodeTelemetryStore:
    def __init__(self, path: Path | None = None, max_items: int = 2000) -> None:
        self._path = path or (_repo_root() / "data" / "node_telemetry_events.json")
        self._max_items = max(100, int(max_items))
        self._items: list[NodeTelemetryRecord] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        items = raw.get("items")
        if not isinstance(items, list):
            return
        loaded: list[NodeTelemetryRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("node_id") or "").strip()
            event_type = str(item.get("event_type") or "").strip()
            received_at = str(item.get("received_at") or "").strip()
            if not (node_id and event_type and received_at):
                continue
            loaded.append(
                NodeTelemetryRecord(
                    node_id=node_id,
                    event_type=event_type,
                    event_state=str(item.get("event_state") or "").strip() or None,
                    message=str(item.get("message") or "").strip() or None,
                    payload=item.get("payload") if isinstance(item.get("payload"), dict) else {},
                    received_at=received_at,
                    schema_version=str(item.get("schema_version") or NODE_TELEMETRY_SCHEMA_VERSION),
                )
            )
        self._items = loaded[-self._max_items :]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": NODE_TELEMETRY_SCHEMA_VERSION,
            "items": [item.to_dict() for item in self._items[-self._max_items :]],
        }
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def append(self, record: NodeTelemetryRecord) -> NodeTelemetryRecord:
        self._items.append(record)
        if len(self._items) > self._max_items:
            self._items = self._items[-self._max_items :]
        self._save()
        return record

    def list(self, *, node_id: str | None = None, limit: int = 100) -> list[NodeTelemetryRecord]:
        node_key = str(node_id or "").strip()
        subset = self._items
        if node_key:
            subset = [item for item in subset if item.node_id == node_key]
        cap = max(1, min(500, int(limit)))
        return list(subset[-cap:])

    def latest_for_node(self, node_id: str) -> NodeTelemetryRecord | None:
        node_key = str(node_id or "").strip()
        if not node_key:
            return None
        for item in reversed(self._items):
            if item.node_id == node_key:
                return item
        return None


class NodeTelemetryService:
    def __init__(self, store: NodeTelemetryStore) -> None:
        self._store = store

    def ingest(
        self,
        *,
        node_id: str,
        event_type: str,
        event_state: str | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> NodeTelemetryRecord:
        node_key = str(node_id or "").strip()
        if not node_key:
            raise ValueError("node_id_required")
        event_key = str(event_type or "").strip().lower()
        if event_key not in ALLOWED_NODE_TELEMETRY_EVENTS:
            raise ValueError("unsupported_event_type")
        body = payload if isinstance(payload, dict) else {}
        sanitized_payload: dict[str, Any] = {}
        for key, value in body.items():
            text_key = str(key or "").strip()
            if not text_key:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                sanitized_payload[text_key] = value
                continue
            if isinstance(value, list):
                sanitized_payload[text_key] = [item for item in value if isinstance(item, (str, int, float, bool))]
                continue
            if isinstance(value, dict):
                flattened: dict[str, Any] = {}
                for sub_key, sub_value in value.items():
                    inner_key = str(sub_key or "").strip()
                    if inner_key and isinstance(sub_value, (str, int, float, bool)):
                        flattened[inner_key] = sub_value
                sanitized_payload[text_key] = flattened
        record = NodeTelemetryRecord(
            node_id=node_key,
            event_type=event_key,
            event_state=str(event_state or "").strip() or None,
            message=str(message or "").strip() or None,
            payload=sanitized_payload,
            received_at=_utcnow_iso(),
        )
        return self._store.append(record)

    def latest_timestamp(self, node_id: str) -> str | None:
        latest = self._store.latest_for_node(node_id)
        return latest.received_at if latest is not None else None

    def list_events(self, *, node_id: str | None = None, limit: int = 100) -> list[NodeTelemetryRecord]:
        return self._store.list(node_id=node_id, limit=limit)

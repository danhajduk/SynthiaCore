from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .sessions import NodeOnboardingSession


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    # backend/app/system/onboarding/trust.py -> onboarding(0), system(1), app(2), backend(3), repo(4)
    return Path(__file__).resolve().parents[4]


@dataclass
class NodeTrustRecord:
    node_id: str
    paired_core_id: str
    node_trust_token: str
    initial_baseline_policy: dict[str, Any]
    baseline_policy_version: str
    operational_mqtt_identity: str
    operational_mqtt_token: str
    operational_mqtt_host: str
    operational_mqtt_port: int
    issued_at: str
    source_session_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "paired_core_id": self.paired_core_id,
            "node_trust_token": self.node_trust_token,
            "initial_baseline_policy": self.initial_baseline_policy,
            "baseline_policy_version": self.baseline_policy_version,
            "operational_mqtt_identity": self.operational_mqtt_identity,
            "operational_mqtt_token": self.operational_mqtt_token,
            "operational_mqtt_host": self.operational_mqtt_host,
            "operational_mqtt_port": self.operational_mqtt_port,
            "issued_at": self.issued_at,
            "source_session_id": self.source_session_id,
        }


class NodeTrustStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (_repo_root() / "data" / "node_trust_records.json")
        self._records_by_node: dict[str, NodeTrustRecord] = {}
        self._session_to_node: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        nodes = raw.get("nodes") if isinstance(raw, dict) else None
        sessions = raw.get("session_to_node") if isinstance(raw, dict) else None
        if isinstance(nodes, list):
            for item in nodes:
                if not isinstance(item, dict):
                    continue
                node_id = str(item.get("node_id") or "").strip()
                source_session_id = str(item.get("source_session_id") or "").strip()
                if not node_id or not source_session_id:
                    continue
                try:
                    rec = NodeTrustRecord(
                        node_id=node_id,
                        paired_core_id=str(item.get("paired_core_id") or "synthia-core"),
                        node_trust_token=str(item.get("node_trust_token") or ""),
                        initial_baseline_policy=item.get("initial_baseline_policy")
                        if isinstance(item.get("initial_baseline_policy"), dict)
                        else {"version": "1", "rules": []},
                        baseline_policy_version=str(item.get("baseline_policy_version") or "1"),
                        operational_mqtt_identity=str(item.get("operational_mqtt_identity") or f"node:{node_id}"),
                        operational_mqtt_token=str(item.get("operational_mqtt_token") or ""),
                        operational_mqtt_host=str(item.get("operational_mqtt_host") or "127.0.0.1"),
                        operational_mqtt_port=int(item.get("operational_mqtt_port") or 1883),
                        issued_at=str(item.get("issued_at") or _utcnow_iso()),
                        source_session_id=source_session_id,
                    )
                except Exception:
                    continue
                self._records_by_node[node_id] = rec
        if isinstance(sessions, dict):
            for key, value in sessions.items():
                sid = str(key or "").strip()
                node_id = str(value or "").strip()
                if sid and node_id:
                    self._session_to_node[sid] = node_id

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "nodes": [item.to_dict() for item in sorted(self._records_by_node.values(), key=lambda x: x.node_id)],
            "session_to_node": dict(sorted(self._session_to_node.items(), key=lambda x: x[0])),
        }
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def get_by_session(self, session_id: str) -> NodeTrustRecord | None:
        sid = str(session_id or "").strip()
        if not sid:
            return None
        node_id = self._session_to_node.get(sid)
        if not node_id:
            return None
        return self._records_by_node.get(node_id)

    def get_by_node(self, node_id: str) -> NodeTrustRecord | None:
        return self._records_by_node.get(str(node_id or "").strip())

    def upsert(self, record: NodeTrustRecord) -> NodeTrustRecord:
        self._records_by_node[record.node_id] = record
        self._session_to_node[record.source_session_id] = record.node_id
        self._save()
        return record


class NodeTrustIssuanceService:
    def __init__(self, store: NodeTrustStore) -> None:
        self._store = store
        self._core_id = str(os.getenv("SYNTHIA_CORE_ID", "synthia-core")).strip() or "synthia-core"
        self._mqtt_host = (
            str(os.getenv("SYNTHIA_NODE_OPERATIONAL_MQTT_HOST", "")).strip()
            or str(os.getenv("SYNTHIA_MQTT_HOST", "127.0.0.1")).strip()
            or "127.0.0.1"
        )
        try:
            self._mqtt_port = int(str(os.getenv("SYNTHIA_NODE_OPERATIONAL_MQTT_PORT", "")).strip() or 1883)
        except Exception:
            self._mqtt_port = 1883

    def issue_for_approved_session(self, session: NodeOnboardingSession) -> dict[str, Any]:
        if str(session.session_state) != "approved":
            raise ValueError("session_not_approved")

        existing = self._store.get_by_session(session.session_id)
        if existing is not None:
            return {"ok": True, "activation": existing.to_dict()}

        node_id = str(session.linked_node_id or "").strip() or f"node-{session.session_id[:12]}"
        baseline_policy_version = "1"
        baseline_policy = {
            "version": baseline_policy_version,
            "rules": [],
        }
        record = NodeTrustRecord(
            node_id=node_id,
            paired_core_id=self._core_id,
            node_trust_token=secrets.token_urlsafe(32),
            initial_baseline_policy=baseline_policy,
            baseline_policy_version=baseline_policy_version,
            operational_mqtt_identity=f"node:{node_id}",
            operational_mqtt_token=secrets.token_urlsafe(32),
            operational_mqtt_host=self._mqtt_host,
            operational_mqtt_port=self._mqtt_port,
            issued_at=_utcnow_iso(),
            source_session_id=session.session_id,
        )
        self._store.upsert(record)
        return {"ok": True, "activation": record.to_dict()}

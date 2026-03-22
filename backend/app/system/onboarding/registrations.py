from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .sessions import NodeOnboardingSession

NODE_REGISTRATION_SCHEMA_VERSION = "2"
REGISTRATION_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "node_name": ("node_name", "requested_node_name"),
    "node_type": ("node_type", "requested_node_type"),
    "node_software_version": ("node_software_version", "requested_node_software_version"),
}
VALID_TRUST_STATUSES = {"pending", "approved", "trusted", "revoked", "rejected"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    # backend/app/system/onboarding/registrations.py -> onboarding(0), system(1), app(2), backend(3), repo(4)
    return Path(__file__).resolve().parents[4]


def _first_text(item: dict[str, object], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


@dataclass
class NodeRegistrationRecord:
    node_id: str
    node_type: str
    node_name: str
    node_software_version: str
    requested_node_type: str | None
    capabilities_summary: list[str]
    trust_status: str
    source_onboarding_session_id: str | None
    approved_by_user_id: str | None
    approved_at: str | None
    created_at: str
    updated_at: str
    requested_hostname: str | None = None
    requested_ui_endpoint: str | None = None
    declared_capabilities: list[str] = field(default_factory=list)
    enabled_providers: list[str] = field(default_factory=list)
    provider_intelligence: list[dict[str, object]] = field(default_factory=list)
    capability_declaration_version: str | None = None
    capability_declaration_timestamp: str | None = None
    capability_profile_id: str | None = None
    schema_version: str = NODE_REGISTRATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "node_name": self.node_name,
            "node_software_version": self.node_software_version,
            "requested_node_type": self.requested_node_type,
            "requested_hostname": self.requested_hostname,
            "requested_ui_endpoint": self.requested_ui_endpoint,
            "capabilities_summary": list(self.capabilities_summary or []),
            "declared_capabilities": list(self.declared_capabilities or []),
            "enabled_providers": list(self.enabled_providers or []),
            "provider_intelligence": [dict(item) for item in self.provider_intelligence if isinstance(item, dict)],
            "capability_declaration_version": self.capability_declaration_version,
            "capability_declaration_timestamp": self.capability_declaration_timestamp,
            "capability_profile_id": self.capability_profile_id,
            "trust_status": self.trust_status,
            "source_onboarding_session_id": self.source_onboarding_session_id,
            "approved_by_user_id": self.approved_by_user_id,
            "approved_at": self.approved_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_api_dict(self) -> dict[str, object]:
        payload = self.to_dict()
        # Compatibility aliases for legacy AI-node naming.
        payload["requested_node_name"] = self.node_name
        payload["requested_node_type"] = str(self.requested_node_type or self.node_type)
        payload["requested_node_software_version"] = self.node_software_version
        payload["requested_hostname"] = self.requested_hostname
        payload["requested_ui_endpoint"] = self.requested_ui_endpoint
        return payload


class NodeRegistrationsStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (_repo_root() / "data" / "node_registrations.json")
        self._records_by_node: dict[str, NodeRegistrationRecord] = {}
        self._session_to_node: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return

        if isinstance(raw, list):
            items = raw
            session_to_node = {}
        elif isinstance(raw, dict):
            items = raw.get("items") if isinstance(raw.get("items"), list) else []
            session_to_node = raw.get("session_to_node") if isinstance(raw.get("session_to_node"), dict) else {}
        else:
            items = []
            session_to_node = {}

        for item in items:
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("node_id") or "").strip()
            node_name = _first_text(item, REGISTRATION_FIELD_ALIASES["node_name"])
            node_type = _first_text(item, REGISTRATION_FIELD_ALIASES["node_type"])
            node_software_version = _first_text(item, REGISTRATION_FIELD_ALIASES["node_software_version"])
            created_at = str(item.get("created_at") or "").strip() or _utcnow_iso()
            updated_at = str(item.get("updated_at") or "").strip() or created_at
            if not (node_id and node_name and node_type and node_software_version):
                continue
            trust_status = str(item.get("trust_status") or "pending").strip().lower() or "pending"
            if trust_status not in VALID_TRUST_STATUSES:
                trust_status = "pending"
            capabilities_raw = item.get("capabilities_summary")
            capabilities = [str(v).strip() for v in capabilities_raw] if isinstance(capabilities_raw, list) else []
            declared_capabilities_raw = item.get("declared_capabilities")
            declared_capabilities = (
                [str(v).strip() for v in declared_capabilities_raw] if isinstance(declared_capabilities_raw, list) else []
            )
            enabled_providers_raw = item.get("enabled_providers")
            enabled_providers = [str(v).strip() for v in enabled_providers_raw] if isinstance(enabled_providers_raw, list) else []
            provider_intelligence_raw = item.get("provider_intelligence")
            provider_intelligence = (
                [dict(v) for v in provider_intelligence_raw if isinstance(v, dict)]
                if isinstance(provider_intelligence_raw, list)
                else []
            )
            record = NodeRegistrationRecord(
                node_id=node_id,
                node_type=node_type,
                node_name=node_name,
                node_software_version=node_software_version,
                requested_node_type=str(item.get("requested_node_type") or "").strip() or None,
                requested_hostname=str(item.get("requested_hostname") or "").strip() or None,
                requested_ui_endpoint=str(item.get("requested_ui_endpoint") or "").strip() or None,
                capabilities_summary=[v for v in capabilities if v],
                declared_capabilities=[v for v in declared_capabilities if v],
                enabled_providers=[v for v in enabled_providers if v],
                provider_intelligence=provider_intelligence,
                capability_declaration_version=str(item.get("capability_declaration_version") or "").strip() or None,
                capability_declaration_timestamp=str(item.get("capability_declaration_timestamp") or "").strip() or None,
                capability_profile_id=str(item.get("capability_profile_id") or "").strip() or None,
                trust_status=trust_status,
                source_onboarding_session_id=str(item.get("source_onboarding_session_id") or "").strip() or None,
                approved_by_user_id=str(item.get("approved_by_user_id") or "").strip() or None,
                approved_at=str(item.get("approved_at") or "").strip() or None,
                created_at=created_at,
                updated_at=updated_at,
                schema_version=str(item.get("schema_version") or NODE_REGISTRATION_SCHEMA_VERSION),
            )
            self._records_by_node[node_id] = record

        for key, value in session_to_node.items():
            session_id = str(key or "").strip()
            node_id = str(value or "").strip()
            if session_id and node_id:
                self._session_to_node[session_id] = node_id

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": NODE_REGISTRATION_SCHEMA_VERSION,
            "field_aliases": {k: list(v) for k, v in REGISTRATION_FIELD_ALIASES.items()},
            "items": [item.to_dict() for item in sorted(self._records_by_node.values(), key=lambda x: x.node_id)],
            "session_to_node": dict(sorted(self._session_to_node.items(), key=lambda x: x[0])),
        }
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def list(self) -> list[NodeRegistrationRecord]:
        return sorted(self._records_by_node.values(), key=lambda item: item.node_id)

    def get(self, node_id: str) -> NodeRegistrationRecord | None:
        return self._records_by_node.get(str(node_id or "").strip())

    def get_by_session(self, session_id: str) -> NodeRegistrationRecord | None:
        sid = str(session_id or "").strip()
        if not sid:
            return None
        node_id = self._session_to_node.get(sid)
        if not node_id:
            return None
        return self._records_by_node.get(node_id)

    def upsert(self, record: NodeRegistrationRecord) -> NodeRegistrationRecord:
        now = _utcnow_iso()
        existing = self._records_by_node.get(record.node_id)
        if existing is not None:
            record.created_at = existing.created_at
            record.updated_at = now
        else:
            record.created_at = record.created_at or now
            record.updated_at = now
        self._records_by_node[record.node_id] = record
        session_id = str(record.source_onboarding_session_id or "").strip()
        if session_id:
            self._session_to_node[session_id] = record.node_id
        self._save()
        return record

    def upsert_from_approved_session(self, session: NodeOnboardingSession) -> NodeRegistrationRecord:
        node_id = str(session.linked_node_id or "").strip()
        if not node_id:
            raise ValueError("linked_node_id_required")
        status = "approved" if str(session.session_state or "").strip() == "approved" else "pending"
        existing = self.get(node_id)
        created_at = existing.created_at if existing is not None else _utcnow_iso()
        record = NodeRegistrationRecord(
            node_id=node_id,
            node_type=str(session.requested_node_type or "").strip(),
            node_name=str(session.requested_node_name or "").strip(),
            node_software_version=str(session.requested_node_software_version or "").strip(),
            requested_node_type=str((session.request_metadata or {}).get("requested_node_type") or "").strip()
            or str(session.requested_node_type or "").strip(),
            requested_hostname=str(session.requested_hostname or "").strip() or None,
            requested_ui_endpoint=str(session.requested_ui_endpoint or "").strip() or None,
            capabilities_summary=[],
            declared_capabilities=[],
            enabled_providers=[],
            provider_intelligence=[],
            capability_declaration_version=None,
            capability_declaration_timestamp=None,
            capability_profile_id=None,
            trust_status=status,
            source_onboarding_session_id=session.session_id,
            approved_by_user_id=str(session.approved_by_user_id or "").strip() or None,
            approved_at=str(session.approved_at or "").strip() or None,
            created_at=created_at,
            updated_at=_utcnow_iso(),
        )
        return self.upsert(record)

    def set_trust_status(
        self,
        node_id: str,
        *,
        trust_status: str,
        approved_by_user_id: str | None = None,
        approved_at: str | None = None,
    ) -> NodeRegistrationRecord | None:
        record = self.get(node_id)
        if record is None:
            return None
        status = str(trust_status or "").strip().lower()
        if status not in VALID_TRUST_STATUSES:
            raise ValueError("trust_status_invalid")
        record.trust_status = status
        if approved_by_user_id is not None:
            record.approved_by_user_id = str(approved_by_user_id or "").strip() or None
        if approved_at is not None:
            record.approved_at = str(approved_at or "").strip() or None
        return self.upsert(record)

    def delete(self, node_id: str) -> NodeRegistrationRecord | None:
        node_key = str(node_id or "").strip()
        if not node_key:
            return None
        record = self._records_by_node.pop(node_key, None)
        if record is None:
            return None
        self._session_to_node = {
            sid: linked_node_id for sid, linked_node_id in self._session_to_node.items() if linked_node_id != node_key
        }
        self._save()
        return record

    def mark_trusted_by_session(self, session_id: str) -> NodeRegistrationRecord | None:
        record = self.get_by_session(session_id)
        if record is None:
            return None
        return self.set_trust_status(
            record.node_id,
            trust_status="trusted",
            approved_by_user_id=record.approved_by_user_id,
            approved_at=record.approved_at,
        )

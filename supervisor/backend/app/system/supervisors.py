from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.admin import require_admin_token

SUPERVISOR_REGISTRY_SCHEMA_VERSION = "1"
SUPERVISOR_ENROLLMENT_SCHEMA_VERSION = "1"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _clean_text(value: object, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _stale_after_s() -> float:
    raw = str(os.getenv("HEXE_SUPERVISOR_FLEET_STALE_S", "60")).strip()
    try:
        return max(1.0, float(raw))
    except Exception:
        return 60.0


def _offline_after_s() -> float:
    raw = str(os.getenv("HEXE_SUPERVISOR_FLEET_OFFLINE_S", "180")).strip()
    try:
        return max(_stale_after_s() + 1.0, float(raw))
    except Exception:
        return 180.0


def _freshness_state(last_seen_at: str | None) -> str:
    if not last_seen_at:
        return "offline"
    try:
        seen = datetime.fromisoformat(str(last_seen_at).replace("Z", "+00:00"))
    except Exception:
        return "offline"
    age_s = max(0.0, (datetime.now(timezone.utc) - seen).total_seconds())
    if age_s >= _offline_after_s():
        return "offline"
    if age_s >= _stale_after_s():
        return "stale"
    return "online"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _default_enrollment_ttl_s() -> int:
    raw = str(os.getenv("HEXE_SUPERVISOR_ENROLLMENT_TTL_S", "900")).strip()
    try:
        return min(max(int(raw), 60), 24 * 60 * 60)
    except Exception:
        return 900


class SupervisorRegistrationRequest(BaseModel):
    supervisor_id: str = Field(..., min_length=1)
    supervisor_name: str | None = None
    supervisor_version: str | None = None
    host_id: str | None = None
    hostname: str | None = None
    api_base_url: str | None = None
    transport: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SupervisorHeartbeatRequest(BaseModel):
    supervisor_id: str = Field(..., min_length=1)
    supervisor_name: str | None = None
    supervisor_version: str | None = None
    host_id: str | None = None
    hostname: str | None = None
    api_base_url: str | None = None
    transport: str | None = None
    health_status: str | None = None
    lifecycle_state: str | None = None
    resources: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    managed_node_count: int | None = None
    registered_runtime_count: int | None = None
    core_runtime_count: int | None = None
    registered_runtimes: list[dict[str, Any]] = Field(default_factory=list)
    core_runtimes: list[dict[str, Any]] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SupervisorEnrollmentTokenCreateRequest(BaseModel):
    supervisor_id: str | None = None
    supervisor_name: str | None = None
    ttl_seconds: int | None = Field(default=None, ge=60, le=24 * 60 * 60)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SupervisorEnrollmentRequest(SupervisorRegistrationRequest):
    enrollment_token: str = Field(..., min_length=16)


@dataclass
class SupervisorFleetRecord:
    supervisor_id: str
    supervisor_name: str
    supervisor_version: str | None
    host_id: str | None
    hostname: str | None
    api_base_url: str | None
    transport: str | None
    trust_status: str
    health_status: str
    lifecycle_state: str
    capabilities: list[str]
    resources: dict[str, Any]
    runtime: dict[str, Any]
    managed_node_count: int | None
    registered_runtime_count: int | None
    core_runtime_count: int | None
    registered_runtimes: list[dict[str, Any]]
    core_runtimes: list[dict[str, Any]]
    metadata: dict[str, Any]
    first_seen_at: str
    last_seen_at: str | None
    updated_at: str
    reporting_token_hash: str | None = None
    schema_version: str = SUPERVISOR_REGISTRY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "supervisor_id": self.supervisor_id,
            "supervisor_name": self.supervisor_name,
            "supervisor_version": self.supervisor_version,
            "host_id": self.host_id,
            "hostname": self.hostname,
            "api_base_url": self.api_base_url,
            "transport": self.transport,
            "trust_status": self.trust_status,
            "health_status": self.health_status,
            "lifecycle_state": self.lifecycle_state,
            "capabilities": list(self.capabilities or []),
            "resources": dict(self.resources or {}),
            "runtime": dict(self.runtime or {}),
            "managed_node_count": self.managed_node_count,
            "registered_runtime_count": self.registered_runtime_count,
            "core_runtime_count": self.core_runtime_count,
            "registered_runtimes": [dict(item or {}) for item in self.registered_runtimes or []],
            "core_runtimes": [dict(item or {}) for item in self.core_runtimes or []],
            "metadata": dict(self.metadata or {}),
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "updated_at": self.updated_at,
            "reporting_token_hash": self.reporting_token_hash,
        }

    def to_api_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("reporting_token_hash", None)
        payload["freshness_state"] = _freshness_state(self.last_seen_at)
        return payload


@dataclass
class SupervisorEnrollmentTokenRecord:
    token_id: str
    token_hash: str
    supervisor_id: str | None
    supervisor_name: str | None
    created_at: str
    expires_at: str
    consumed_at: str | None = None
    consumed_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SUPERVISOR_ENROLLMENT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "token_id": self.token_id,
            "token_hash": self.token_hash,
            "supervisor_id": self.supervisor_id,
            "supervisor_name": self.supervisor_name,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "consumed_at": self.consumed_at,
            "consumed_by": self.consumed_by,
            "metadata": dict(self.metadata or {}),
        }

    def to_api_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("token_hash", None)
        return payload


class SupervisorFleetStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (_repo_root() / "data" / "supervisor_registrations.json")
        self._records: dict[str, SupervisorFleetRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        items = raw.get("items") if isinstance(raw, dict) and isinstance(raw.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            supervisor_id = _clean_text(item.get("supervisor_id"))
            if not supervisor_id:
                continue
            first_seen_at = _clean_text(item.get("first_seen_at"), _utcnow_iso())
            updated_at = _clean_text(item.get("updated_at"), first_seen_at)
            record = SupervisorFleetRecord(
                supervisor_id=supervisor_id,
                supervisor_name=_clean_text(item.get("supervisor_name"), supervisor_id),
                supervisor_version=_clean_text(item.get("supervisor_version")) or None,
                host_id=_clean_text(item.get("host_id")) or None,
                hostname=_clean_text(item.get("hostname")) or None,
                api_base_url=_clean_text(item.get("api_base_url")) or None,
                transport=_clean_text(item.get("transport")) or None,
                trust_status=_clean_text(item.get("trust_status"), "trusted"),
                health_status=_clean_text(item.get("health_status"), "unknown"),
                lifecycle_state=_clean_text(item.get("lifecycle_state"), "unknown"),
                capabilities=[_clean_text(value) for value in item.get("capabilities", []) if _clean_text(value)]
                if isinstance(item.get("capabilities"), list)
                else [],
                resources=dict(item.get("resources") or {}) if isinstance(item.get("resources"), dict) else {},
                runtime=dict(item.get("runtime") or {}) if isinstance(item.get("runtime"), dict) else {},
                managed_node_count=item.get("managed_node_count") if isinstance(item.get("managed_node_count"), int) else None,
                registered_runtime_count=(
                    item.get("registered_runtime_count") if isinstance(item.get("registered_runtime_count"), int) else None
                ),
                core_runtime_count=item.get("core_runtime_count") if isinstance(item.get("core_runtime_count"), int) else None,
                registered_runtimes=[
                    dict(value) for value in item.get("registered_runtimes", []) if isinstance(value, dict)
                ]
                if isinstance(item.get("registered_runtimes"), list)
                else [],
                core_runtimes=[dict(value) for value in item.get("core_runtimes", []) if isinstance(value, dict)]
                if isinstance(item.get("core_runtimes"), list)
                else [],
                metadata=dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {},
                first_seen_at=first_seen_at,
                last_seen_at=_clean_text(item.get("last_seen_at")) or None,
                updated_at=updated_at,
                reporting_token_hash=_clean_text(item.get("reporting_token_hash")) or None,
                schema_version=_clean_text(item.get("schema_version"), SUPERVISOR_REGISTRY_SCHEMA_VERSION),
            )
            self._records[supervisor_id] = record

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SUPERVISOR_REGISTRY_SCHEMA_VERSION,
            "items": [record.to_dict() for record in sorted(self._records.values(), key=lambda item: item.supervisor_id)],
        }
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def list(self) -> list[SupervisorFleetRecord]:
        return sorted(self._records.values(), key=lambda item: item.supervisor_id)

    def get(self, supervisor_id: str) -> SupervisorFleetRecord | None:
        return self._records.get(_clean_text(supervisor_id))

    def delete(self, supervisor_id: str) -> SupervisorFleetRecord | None:
        key = _clean_text(supervisor_id)
        if not key:
            return None
        record = self._records.pop(key, None)
        if record is not None:
            self._save()
        return record

    def register(self, body: SupervisorRegistrationRequest) -> SupervisorFleetRecord:
        now = _utcnow_iso()
        existing = self.get(body.supervisor_id)
        record = SupervisorFleetRecord(
            supervisor_id=_clean_text(body.supervisor_id),
            supervisor_name=_clean_text(body.supervisor_name, body.supervisor_id),
            supervisor_version=_clean_text(body.supervisor_version) or (existing.supervisor_version if existing else None),
            host_id=_clean_text(body.host_id) or (existing.host_id if existing else None),
            hostname=_clean_text(body.hostname) or (existing.hostname if existing else None),
            api_base_url=_clean_text(body.api_base_url) or (existing.api_base_url if existing else None),
            transport=_clean_text(body.transport) or (existing.transport if existing else None),
            trust_status="trusted",
            health_status=existing.health_status if existing else "registered",
            lifecycle_state=existing.lifecycle_state if existing else "unknown",
            capabilities=[_clean_text(value) for value in body.capabilities if _clean_text(value)]
            or (existing.capabilities if existing else []),
            resources=existing.resources if existing else {},
            runtime=existing.runtime if existing else {},
            managed_node_count=existing.managed_node_count if existing else None,
            registered_runtime_count=existing.registered_runtime_count if existing else None,
            core_runtime_count=existing.core_runtime_count if existing else None,
            registered_runtimes=existing.registered_runtimes if existing else [],
            core_runtimes=existing.core_runtimes if existing else [],
            metadata=dict(body.metadata or {}) or (existing.metadata if existing else {}),
            first_seen_at=existing.first_seen_at if existing else now,
            last_seen_at=existing.last_seen_at if existing else None,
            updated_at=now,
            reporting_token_hash=existing.reporting_token_hash if existing else None,
        )
        self._records[record.supervisor_id] = record
        self._save()
        return record

    def heartbeat(self, body: SupervisorHeartbeatRequest) -> SupervisorFleetRecord:
        now = _utcnow_iso()
        existing = self.get(body.supervisor_id)
        base = existing or self.register(
            SupervisorRegistrationRequest(
                supervisor_id=body.supervisor_id,
                supervisor_name=body.supervisor_name,
                supervisor_version=body.supervisor_version,
                host_id=body.host_id,
                hostname=body.hostname,
                api_base_url=body.api_base_url,
                transport=body.transport,
                capabilities=body.capabilities,
                metadata=body.metadata,
            )
        )
        record = SupervisorFleetRecord(
            supervisor_id=base.supervisor_id,
            supervisor_name=_clean_text(body.supervisor_name, base.supervisor_name),
            supervisor_version=_clean_text(body.supervisor_version) or base.supervisor_version,
            host_id=_clean_text(body.host_id) or base.host_id,
            hostname=_clean_text(body.hostname) or base.hostname,
            api_base_url=_clean_text(body.api_base_url) or base.api_base_url,
            transport=_clean_text(body.transport) or base.transport,
            trust_status=base.trust_status,
            health_status=_clean_text(body.health_status, base.health_status),
            lifecycle_state=_clean_text(body.lifecycle_state, base.lifecycle_state),
            capabilities=[_clean_text(value) for value in body.capabilities if _clean_text(value)] or base.capabilities,
            resources=dict(body.resources or {}),
            runtime=dict(body.runtime or {}),
            managed_node_count=body.managed_node_count,
            registered_runtime_count=body.registered_runtime_count,
            core_runtime_count=body.core_runtime_count,
            registered_runtimes=[dict(item) for item in body.registered_runtimes if isinstance(item, dict)],
            core_runtimes=[dict(item) for item in body.core_runtimes if isinstance(item, dict)],
            metadata={**dict(base.metadata or {}), **dict(body.metadata or {})},
            first_seen_at=base.first_seen_at,
            last_seen_at=now,
            updated_at=now,
            reporting_token_hash=base.reporting_token_hash,
        )
        self._records[record.supervisor_id] = record
        self._save()
        return record

    def set_reporting_token(self, supervisor_id: str, token: str) -> SupervisorFleetRecord:
        record = self.get(supervisor_id)
        if record is None:
            raise HTTPException(status_code=404, detail="supervisor_not_found")
        record.reporting_token_hash = _sha256_text(token)
        record.updated_at = _utcnow_iso()
        self._records[record.supervisor_id] = record
        self._save()
        return record

    def verify_reporting_token(self, supervisor_id: str, token: str | None) -> bool:
        if not token:
            return False
        record = self.get(supervisor_id)
        expected = record.reporting_token_hash if record else None
        if not expected:
            return False
        return hmac.compare_digest(expected, _sha256_text(token))


class SupervisorEnrollmentTokenStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (_repo_root() / "data" / "supervisor_enrollment_tokens.json")
        self._records: dict[str, SupervisorEnrollmentTokenRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        items = raw.get("items") if isinstance(raw, dict) and isinstance(raw.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            token_id = _clean_text(item.get("token_id"))
            token_hash = _clean_text(item.get("token_hash"))
            if not token_id or not token_hash:
                continue
            self._records[token_id] = SupervisorEnrollmentTokenRecord(
                token_id=token_id,
                token_hash=token_hash,
                supervisor_id=_clean_text(item.get("supervisor_id")) or None,
                supervisor_name=_clean_text(item.get("supervisor_name")) or None,
                created_at=_clean_text(item.get("created_at"), _utcnow_iso()),
                expires_at=_clean_text(item.get("expires_at"), _utcnow_iso()),
                consumed_at=_clean_text(item.get("consumed_at")) or None,
                consumed_by=_clean_text(item.get("consumed_by")) or None,
                metadata=dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {},
                schema_version=_clean_text(item.get("schema_version"), SUPERVISOR_ENROLLMENT_SCHEMA_VERSION),
            )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SUPERVISOR_ENROLLMENT_SCHEMA_VERSION,
            "items": [record.to_dict() for record in sorted(self._records.values(), key=lambda item: item.token_id)],
        }
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def create(self, body: SupervisorEnrollmentTokenCreateRequest) -> tuple[SupervisorEnrollmentTokenRecord, str]:
        now = datetime.now(timezone.utc)
        ttl_s = body.ttl_seconds or _default_enrollment_ttl_s()
        raw_token = f"hexe_sup_enroll_{secrets.token_urlsafe(32)}"
        record = SupervisorEnrollmentTokenRecord(
            token_id=secrets.token_urlsafe(12),
            token_hash=_sha256_text(raw_token),
            supervisor_id=_clean_text(body.supervisor_id) or None,
            supervisor_name=_clean_text(body.supervisor_name) or None,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=ttl_s)).isoformat(),
            metadata=dict(body.metadata or {}),
        )
        self._records[record.token_id] = record
        self._save()
        return record, raw_token

    def consume(self, token: str, *, supervisor_id: str) -> SupervisorEnrollmentTokenRecord:
        token_hash = _sha256_text(_clean_text(token))
        matched: SupervisorEnrollmentTokenRecord | None = None
        for record in self._records.values():
            if hmac.compare_digest(record.token_hash, token_hash):
                matched = record
                break
        if matched is None:
            raise HTTPException(status_code=401, detail="invalid_enrollment_token")
        if matched.consumed_at:
            raise HTTPException(status_code=409, detail="enrollment_token_already_used")
        expires_at = _parse_iso(matched.expires_at)
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="enrollment_token_expired")
        expected_supervisor_id = _clean_text(matched.supervisor_id)
        actual_supervisor_id = _clean_text(supervisor_id)
        if expected_supervisor_id and expected_supervisor_id != actual_supervisor_id:
            raise HTTPException(status_code=403, detail="enrollment_token_supervisor_mismatch")
        matched.consumed_at = _utcnow_iso()
        matched.consumed_by = actual_supervisor_id
        self._records[matched.token_id] = matched
        self._save()
        return matched


def build_supervisors_router(
    store: SupervisorFleetStore | None = None,
    enrollment_store: SupervisorEnrollmentTokenStore | None = None,
) -> APIRouter:
    router = APIRouter()
    registry = store or SupervisorFleetStore()
    enrollment_registry = enrollment_store or SupervisorEnrollmentTokenStore()

    def authorize_report(
        *,
        supervisor_id: str,
        request: Request,
        x_admin_token: str | None,
        x_supervisor_token: str | None,
    ) -> None:
        if x_admin_token:
            require_admin_token(x_admin_token, request)
            return
        if x_supervisor_token:
            if registry.verify_reporting_token(supervisor_id, x_supervisor_token):
                return
            raise HTTPException(status_code=401, detail="invalid_supervisor_token")
        require_admin_token(x_admin_token, request)

    @router.get("/supervisors")
    def list_supervisors(request: Request, x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
        require_admin_token(x_admin_token, request)
        return {"items": [record.to_api_dict() for record in registry.list()]}

    @router.post("/supervisors/enrollment-tokens")
    def create_supervisor_enrollment_token(
        body: SupervisorEnrollmentTokenCreateRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin_token(x_admin_token, request)
        record, token = enrollment_registry.create(body)
        return {"ok": True, "enrollment_token": token, "one_time_token": token, "token": record.to_api_dict()}

    @router.post("/supervisors/enroll")
    def enroll_supervisor(body: SupervisorEnrollmentRequest) -> dict[str, Any]:
        enrollment_registry.consume(body.enrollment_token, supervisor_id=body.supervisor_id)
        reporting_token = f"hexe_sup_report_{secrets.token_urlsafe(32)}"
        record = registry.register(
            SupervisorRegistrationRequest(
                supervisor_id=body.supervisor_id,
                supervisor_name=body.supervisor_name,
                supervisor_version=body.supervisor_version,
                host_id=body.host_id,
                hostname=body.hostname,
                api_base_url=body.api_base_url,
                transport=body.transport,
                capabilities=body.capabilities,
                metadata=body.metadata,
            )
        )
        record = registry.set_reporting_token(record.supervisor_id, reporting_token)
        return {
            "ok": True,
            "supervisor": record.to_api_dict(),
            "reporting_token": reporting_token,
            "token_type": "supervisor-reporting",
        }

    @router.get("/supervisors/{supervisor_id}")
    def get_supervisor(
        supervisor_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin_token(x_admin_token, request)
        record = registry.get(supervisor_id)
        if record is None:
            raise HTTPException(status_code=404, detail="supervisor_not_found")
        return {"supervisor": record.to_api_dict()}

    @router.post("/supervisors/register")
    def register_supervisor(
        body: SupervisorRegistrationRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
        x_supervisor_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize_report(
            supervisor_id=body.supervisor_id,
            request=request,
            x_admin_token=x_admin_token,
            x_supervisor_token=x_supervisor_token,
        )
        record = registry.register(body)
        return {"ok": True, "supervisor": record.to_api_dict()}

    @router.post("/supervisors/heartbeat")
    def heartbeat_supervisor(
        body: SupervisorHeartbeatRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
        x_supervisor_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize_report(
            supervisor_id=body.supervisor_id,
            request=request,
            x_admin_token=x_admin_token,
            x_supervisor_token=x_supervisor_token,
        )
        record = registry.heartbeat(body)
        return {"ok": True, "supervisor": record.to_api_dict()}

    @router.delete("/supervisors/{supervisor_id}")
    def delete_supervisor(
        supervisor_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin_token(x_admin_token, request)
        record = registry.delete(supervisor_id)
        if record is None:
            raise HTTPException(status_code=404, detail="supervisor_not_found")
        return {"ok": True, "deleted": record.to_api_dict()}

    return router

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


INTERNAL_EVENT_TOPIC = "synthia/notify/internal/event"
INTERNAL_STATE_TOPIC = "synthia/notify/internal/state"
INTERNAL_POPUP_TOPIC = "synthia/notify/internal/popup"

_EXTERNAL_TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _parse_datetime(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("datetime value is required")
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class NotificationSourceKind(str, Enum):
    CORE = "core"
    ADDON = "addon"
    NODE = "node"
    SERVICE = "service"
    SYSTEM = "system"
    USER = "user"


class NotificationSeverity(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationChannel(str, Enum):
    POPUP = "popup"
    EVENT = "event"
    STATE = "state"
    EXTERNAL = "external"


class NotificationSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: NotificationSourceKind
    id: str = Field(..., min_length=1)
    component: str | None = None
    label: str | None = None
    host: str | None = None
    user: str | None = None
    session: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NotificationTargets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    broadcast: bool = False
    users: list[str] = Field(default_factory=list)
    hosts: list[str] = Field(default_factory=list)
    sessions: list[str] = Field(default_factory=list)
    external: list[str] = Field(default_factory=list)

    @field_validator("users", "hosts", "sessions", "external", mode="before")
    @classmethod
    def _normalize_target_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("target list must be a list or string")
        out: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            out.append(text)
            seen.add(text)
        return out

    @model_validator(mode="after")
    def _ensure_target_scope(self) -> "NotificationTargets":
        if self.broadcast or self.users or self.hosts or self.sessions or self.external:
            return self
        raise ValueError("at least one target list must be non-empty or broadcast must be true")


class NotificationDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: NotificationSeverity = NotificationSeverity.INFO
    priority: NotificationPriority = NotificationPriority.NORMAL
    channels: list[NotificationChannel] = Field(default_factory=list)
    ttl_seconds: int | None = Field(default=None, ge=1)
    dedupe_key: str | None = None

    @field_validator("channels", mode="before")
    @classmethod
    def _normalize_channels(cls, value: Any) -> list[NotificationChannel]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        return value


class NotificationContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    subtitle: str | None = None
    message: str | None = None
    body: str | None = None

    def has_payload(self) -> bool:
        return any(bool(str(value).strip()) for value in (self.title, self.subtitle, self.message, self.body))


class NotificationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str | None = None
    action: str | None = None
    summary: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _ensure_not_empty(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if any(bool(str(value.get(key) or "").strip()) for key in ("event_type", "action", "summary")):
            return value
        if value.get("attributes"):
            return value
        raise ValueError("event payload cannot be empty when present")


class NotificationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state_type: str | None = None
    status: str | None = None
    current: str | None = None
    previous: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _ensure_not_empty(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if any(bool(str(value.get(key) or "").strip()) for key in ("state_type", "status", "current", "previous")):
            return value
        if value.get("attributes"):
            return value
        raise ValueError("state payload cannot be empty when present")


class NotificationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=_utcnow_iso)
    source: NotificationSource
    targets: NotificationTargets
    delivery: NotificationDelivery = Field(default_factory=NotificationDelivery)
    content: NotificationContent | None = None
    event: NotificationEvent | None = None
    state: NotificationState | None = None
    data: dict[str, Any] | None = None

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: str) -> str:
        return _parse_datetime(value).isoformat()

    @model_validator(mode="after")
    def _ensure_payload_present(self) -> "NotificationMessage":
        has_content = self.content is not None and self.content.has_payload()
        has_event = self.event is not None
        has_state = self.state is not None
        has_data = bool(self.data)
        if has_content or has_event or has_state or has_data:
            return self
        raise ValueError("at least one payload section must exist: content, event, state, or data")

    def to_payload(self, *, exclude_none: bool = True) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=exclude_none)

    def to_json(self, *, exclude_none: bool = True) -> str:
        return json.dumps(self.to_payload(exclude_none=exclude_none), sort_keys=True)

    def is_expired(self, *, at: datetime | None = None) -> bool:
        ttl_seconds = self.delivery.ttl_seconds
        if ttl_seconds is None:
            return False
        created_at = _parse_datetime(self.created_at)
        now = at.astimezone(timezone.utc) if at is not None else _utcnow()
        return now >= created_at + timedelta(seconds=ttl_seconds)

    @classmethod
    def from_json(cls, payload: str | bytes | bytearray) -> "NotificationMessage":
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        return cls.model_validate_json(payload)


def notification_message_from_json(payload: str | bytes | bytearray) -> NotificationMessage:
    return NotificationMessage.from_json(payload)


def notification_message_to_json(message: NotificationMessage, *, exclude_none: bool = True) -> str:
    return message.to_json(exclude_none=exclude_none)


def is_notification_expired(message: NotificationMessage, *, at: datetime | None = None) -> bool:
    return message.is_expired(at=at)


def external_notification_topic(target: str) -> str:
    clean = str(target or "").strip()
    if not _EXTERNAL_TARGET_RE.match(clean):
        raise ValueError("external target must match [A-Za-z0-9_.-]{1,64}")
    return f"synthia/notify/external/{clean}"

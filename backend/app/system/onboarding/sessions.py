from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

VALID_SESSION_STATES = {
    "pending",
    "approved",
    "rejected",
    "expired",
    "consumed",
    "cancelled",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _repo_root() -> Path:
    # backend/app/system/onboarding/sessions.py -> onboarding(0), system(1), app(2), backend(3), repo(4)
    return Path(__file__).resolve().parents[4]


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _parse_iso(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class NodeOnboardingSession:
    session_id: str
    session_state: str
    node_nonce: str
    requested_node_name: str
    requested_node_type: str
    requested_node_software_version: str
    requested_hostname: str | None
    requested_ui_endpoint: str | None
    requested_api_base_url: str | None
    requested_from_ip: str | None
    request_metadata: dict[str, Any]
    created_at: str
    expires_at: str
    approved_at: str | None
    rejected_at: str | None
    approved_by_user_id: str | None
    rejection_reason: str | None
    linked_node_id: str | None
    final_payload_consumed_at: str | None
    state_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_state": self.session_state,
            "node_nonce": self.node_nonce,
            "requested_node_name": self.requested_node_name,
            "requested_node_type": self.requested_node_type,
            "requested_node_software_version": self.requested_node_software_version,
            "requested_hostname": self.requested_hostname,
            "requested_ui_endpoint": self.requested_ui_endpoint,
            "requested_api_base_url": self.requested_api_base_url,
            "requested_from_ip": self.requested_from_ip,
            "request_metadata": dict(self.request_metadata or {}),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "approved_at": self.approved_at,
            "rejected_at": self.rejected_at,
            "approved_by_user_id": self.approved_by_user_id,
            "rejection_reason": self.rejection_reason,
            "linked_node_id": self.linked_node_id,
            "final_payload_consumed_at": self.final_payload_consumed_at,
            "state_history": list(self.state_history or []),
        }


class NodeOnboardingSessionsStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (_repo_root() / "data" / "node_onboarding_sessions.json")
        self._archive_path = self._path.with_suffix(self._path.suffix + ".archive.jsonl")
        self._sessions: dict[str, NodeOnboardingSession] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict):
                continue
            state = str(item.get("session_state") or "").strip()
            if state not in VALID_SESSION_STATES:
                continue
            session_id = str(item.get("session_id") or "").strip()
            node_nonce = str(item.get("node_nonce") or "").strip()
            node_name = str(item.get("requested_node_name") or "").strip()
            node_type = str(item.get("requested_node_type") or "").strip()
            node_version = str(item.get("requested_node_software_version") or "").strip()
            created_at = str(item.get("created_at") or "").strip()
            expires_at = str(item.get("expires_at") or "").strip()
            if not (session_id and node_nonce and node_name and node_type and node_version and created_at and expires_at):
                continue
            metadata = item.get("request_metadata")
            history = item.get("state_history")
            self._sessions[session_id] = NodeOnboardingSession(
                session_id=session_id,
                session_state=state,
                node_nonce=node_nonce,
                requested_node_name=node_name,
                requested_node_type=node_type,
                requested_node_software_version=node_version,
                requested_hostname=(str(item.get("requested_hostname")).strip() if item.get("requested_hostname") else None),
                requested_ui_endpoint=(
                    str(item.get("requested_ui_endpoint")).strip() if item.get("requested_ui_endpoint") else None
                ),
                requested_api_base_url=(
                    str(item.get("requested_api_base_url")).strip() if item.get("requested_api_base_url") else None
                ),
                requested_from_ip=(str(item.get("requested_from_ip")).strip() if item.get("requested_from_ip") else None),
                request_metadata=metadata if isinstance(metadata, dict) else {},
                created_at=created_at,
                expires_at=expires_at,
                approved_at=(str(item.get("approved_at")).strip() if item.get("approved_at") else None),
                rejected_at=(str(item.get("rejected_at")).strip() if item.get("rejected_at") else None),
                approved_by_user_id=(str(item.get("approved_by_user_id")).strip() if item.get("approved_by_user_id") else None),
                rejection_reason=(str(item.get("rejection_reason")).strip() if item.get("rejection_reason") else None),
                linked_node_id=(str(item.get("linked_node_id")).strip() if item.get("linked_node_id") else None),
                final_payload_consumed_at=(
                    str(item.get("final_payload_consumed_at")).strip()
                    if item.get("final_payload_consumed_at")
                    else None
                ),
                state_history=history if isinstance(history, list) else [],
            )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [x.to_dict() for x in sorted(self._sessions.values(), key=lambda s: s.created_at)]
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _get(self, session_id: str) -> NodeOnboardingSession:
        key = str(session_id or "").strip()
        if not key:
            raise ValueError("session_id_required")
        session = self._sessions.get(key)
        if session is None:
            raise KeyError("session_not_found")
        return session

    def _record_transition(
        self,
        session: NodeOnboardingSession,
        *,
        from_state: str,
        to_state: str,
        actor_id: str | None,
        reason: str | None,
    ) -> None:
        session.state_history.append(
            {
                "at": _utcnow_iso(),
                "from_state": from_state,
                "to_state": to_state,
                "actor_id": actor_id,
                "reason": reason,
            }
        )

    def _transition(
        self,
        session: NodeOnboardingSession,
        *,
        next_state: str,
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> NodeOnboardingSession:
        prev = session.session_state
        if prev == next_state:
            return session
        allowed = {
            "pending": {"approved", "rejected", "expired", "cancelled"},
            "approved": {"consumed"},
            "rejected": set(),
            "expired": set(),
            "consumed": set(),
            "cancelled": set(),
        }
        if next_state not in allowed.get(prev, set()):
            raise ValueError("invalid_state_transition")
        session.session_state = next_state
        self._record_transition(session, from_state=prev, to_state=next_state, actor_id=actor_id, reason=reason)
        return session

    def start_session(
        self,
        *,
        node_nonce: str,
        requested_node_name: str,
        requested_node_type: str,
        requested_node_software_version: str,
        requested_hostname: str | None = None,
        requested_ui_endpoint: str | None = None,
        requested_api_base_url: str | None = None,
        requested_from_ip: str | None = None,
        request_metadata: dict[str, Any] | None = None,
        ttl_seconds: int = 900,
    ) -> NodeOnboardingSession:
        nonce = str(node_nonce or "").strip()
        node_name = str(requested_node_name or "").strip()
        node_type = str(requested_node_type or "").strip()
        node_version = str(requested_node_software_version or "").strip()
        if not nonce:
            raise ValueError("node_nonce_required")
        if not node_name:
            raise ValueError("requested_node_name_required")
        if not node_type:
            raise ValueError("requested_node_type_required")
        if not node_version:
            raise ValueError("requested_node_software_version_required")
        ttl = int(ttl_seconds)
        if ttl <= 0:
            raise ValueError("ttl_seconds_invalid")

        now = _utcnow()
        session_id = secrets.token_urlsafe(24)
        session = NodeOnboardingSession(
            session_id=session_id,
            session_state="pending",
            node_nonce=nonce,
            requested_node_name=node_name,
            requested_node_type=node_type,
            requested_node_software_version=node_version,
            requested_hostname=(str(requested_hostname).strip() if requested_hostname else None),
            requested_ui_endpoint=(str(requested_ui_endpoint).strip() if requested_ui_endpoint else None),
            requested_api_base_url=(str(requested_api_base_url).strip() if requested_api_base_url else None),
            requested_from_ip=(str(requested_from_ip).strip() if requested_from_ip else None),
            request_metadata=dict(request_metadata or {}),
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=ttl)).isoformat(),
            approved_at=None,
            rejected_at=None,
            approved_by_user_id=None,
            rejection_reason=None,
            linked_node_id=None,
            final_payload_consumed_at=None,
            state_history=[],
        )
        self._record_transition(session, from_state="none", to_state="pending", actor_id=None, reason="session_created")
        self._sessions[session_id] = session
        self._save()
        return session

    def get(self, session_id: str) -> NodeOnboardingSession:
        return self._get(session_id)

    def list_sessions(self, *, state: str | None = None) -> list[NodeOnboardingSession]:
        selected = list(self._sessions.values())
        if state is not None:
            state_key = str(state).strip()
            selected = [item for item in selected if item.session_state == state_key]
        return sorted(selected, key=lambda item: item.created_at)

    def find_active_by_node_nonce(self, node_nonce: str) -> NodeOnboardingSession | None:
        target = str(node_nonce or "").strip()
        if not target:
            return None
        now = _utcnow()
        matches = []
        for session in self._sessions.values():
            if session.node_nonce != target:
                continue
            if session.session_state not in {"pending", "approved"}:
                continue
            expiry = _parse_iso(session.expires_at)
            if expiry is not None and expiry <= now:
                continue
            matches.append(session)
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.created_at)[-1]

    def approve_session(self, session_id: str, *, approved_by_user_id: str, linked_node_id: str) -> NodeOnboardingSession:
        approver = str(approved_by_user_id or "").strip()
        node_id = str(linked_node_id or "").strip()
        if not approver:
            raise ValueError("approved_by_user_id_required")
        if not node_id:
            raise ValueError("linked_node_id_required")
        session = self._get(session_id)
        self._transition(session, next_state="approved", actor_id=approver, reason="operator_approved")
        now = _utcnow_iso()
        session.approved_at = now
        session.approved_by_user_id = approver
        session.linked_node_id = node_id
        session.rejected_at = None
        session.rejection_reason = None
        self._save()
        return session

    def reject_session(
        self,
        session_id: str,
        *,
        rejected_by_user_id: str,
        rejection_reason: str | None = None,
    ) -> NodeOnboardingSession:
        actor = str(rejected_by_user_id or "").strip()
        if not actor:
            raise ValueError("rejected_by_user_id_required")
        session = self._get(session_id)
        self._transition(session, next_state="rejected", actor_id=actor, reason="operator_rejected")
        session.rejected_at = _utcnow_iso()
        session.rejection_reason = str(rejection_reason or "").strip() or None
        self._save()
        return session

    def consume_final_payload(self, session_id: str, *, actor_id: str | None = "node_finalization") -> NodeOnboardingSession:
        session = self._get(session_id)
        if session.session_state == "consumed":
            raise ValueError("final_payload_already_consumed")
        self._transition(session, next_state="consumed", actor_id=actor_id, reason="final_payload_consumed")
        session.final_payload_consumed_at = _utcnow_iso()
        self._save()
        return session

    def expire_stale_sessions(self, *, now: datetime | None = None) -> int:
        current = now or _utcnow()
        changed = 0
        for session in self._sessions.values():
            if session.session_state != "pending":
                continue
            expiry = _parse_iso(session.expires_at)
            if expiry is None or expiry > current:
                continue
            self._transition(session, next_state="expired", actor_id="system", reason="session_ttl_elapsed")
            changed += 1
        if changed:
            self._save()
        return changed

    def cancel_session(self, session_id: str, *, actor_id: str) -> NodeOnboardingSession:
        actor = str(actor_id or "").strip()
        if not actor:
            raise ValueError("actor_id_required")
        session = self._get(session_id)
        self._transition(session, next_state="cancelled", actor_id=actor, reason="session_cancelled")
        self._save()
        return session

    def archive_and_prune_terminal_sessions(self, *, retain_days: int = 30, now: datetime | None = None) -> int:
        keep_days = max(int(retain_days), 1)
        cutoff = (now or _utcnow()) - timedelta(days=keep_days)
        terminal_states = {"rejected", "expired", "consumed", "cancelled"}
        remove_ids: list[str] = []
        archived_count = 0
        for session in self._sessions.values():
            if session.session_state not in terminal_states:
                continue
            refs = [
                session.final_payload_consumed_at,
                session.rejected_at,
                session.approved_at,
                session.expires_at,
                session.created_at,
            ]
            last_ts = None
            for item in refs:
                parsed = _parse_iso(item)
                if parsed is not None:
                    last_ts = parsed
                    break
            if last_ts is None or last_ts > cutoff:
                continue
            self._archive_path.parent.mkdir(parents=True, exist_ok=True)
            with self._archive_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(session.to_dict(), sort_keys=True))
                handle.write("\n")
            remove_ids.append(session.session_id)
            archived_count += 1
        if not remove_ids:
            return 0
        for sid in remove_ids:
            self._sessions.pop(sid, None)
        self._save()
        return archived_count

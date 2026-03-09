from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import re
from datetime import datetime, timezone

from .integration_models import MqttIntegrationState, MqttPrincipal


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_username(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip())
    clean = clean.strip("_.-")
    return clean[:64] if clean else "mqtt_user"


def _hash_password(password: str, *, iterations: int = 101_000) -> str:
    salt = secrets.token_bytes(12)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, iterations)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"$7${int(iterations)}${salt_b64}${digest_b64}"


class MqttCredentialStore:
    def __init__(self, path: str) -> None:
        self.path = path
        base_dir = os.path.dirname(path)
        if base_dir:
            os.makedirs(base_dir, exist_ok=True)

    def render_password_file(self, state: MqttIntegrationState) -> str:
        payload = self._load_payload()
        credentials = dict(payload.get("credentials") or {})
        next_credentials: dict[str, dict[str, str]] = {}
        lines = ["# managed by synthia core mqtt credential store"]

        for principal in sorted(state.principals.values(), key=lambda item: item.principal_id):
            if not self._principal_requires_credential(principal):
                continue
            item = credentials.get(principal.principal_id)
            if not isinstance(item, dict):
                item = {}
            username = self._principal_username(principal, fallback=item.get("username"))
            password = str(item.get("password") or "").strip() or secrets.token_urlsafe(24)
            password_hash = _hash_password(password)
            next_credentials[principal.principal_id] = {
                "principal_id": principal.principal_id,
                "principal_type": principal.principal_type,
                "username": username,
                "password": password,
                "password_hash": password_hash,
                "updated_at": _utcnow_iso(),
            }
            lines.append(f"{username}:{password_hash}")

        self._save_payload(
            {
                "schema_version": 1,
                "updated_at": _utcnow_iso(),
                "credentials": next_credentials,
            }
        )
        return "\n".join(lines) + "\n"

    def rotate_principal(self, principal_id: str) -> bool:
        payload = self._load_payload()
        credentials = dict(payload.get("credentials") or {})
        if principal_id not in credentials:
            return False
        del credentials[principal_id]
        self._save_payload(
            {
                "schema_version": 1,
                "updated_at": _utcnow_iso(),
                "credentials": credentials,
            }
        )
        return True

    def _principal_username(self, principal: MqttPrincipal, *, fallback: str | None) -> str:
        preferred = str(principal.username or "").strip()
        if preferred:
            return _sanitize_username(preferred)
        if fallback and str(fallback).strip():
            return _sanitize_username(str(fallback))
        prefix = "sx"
        if principal.principal_type == "generic_user":
            prefix = "gu"
        elif principal.principal_type == "synthia_node":
            prefix = "sn"
        return _sanitize_username(f"{prefix}_{principal.logical_identity}")

    @staticmethod
    def _principal_requires_credential(principal: MqttPrincipal) -> bool:
        if principal.principal_type not in {"synthia_addon", "synthia_node", "generic_user"}:
            return False
        if principal.status in {"revoked", "expired"}:
            return False
        return True

    def _load_payload(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save_payload(self, payload: dict) -> None:
        temp = f"{self.path}.tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(temp, self.path)

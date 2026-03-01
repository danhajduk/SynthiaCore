from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel

router = APIRouter()

LOG_FILE = Path("/tmp/synthia_update.log")
ADMIN_SESSION_COOKIE = "synthia_admin_session"
DEFAULT_SESSION_TTL_SECONDS = 8 * 60 * 60


class AdminSessionLoginRequest(BaseModel):
    token: str


def _admin_token_expected() -> str:
    return os.getenv("SYNTHIA_ADMIN_TOKEN", "")


def _cookie_secure() -> bool:
    raw = os.getenv("SYNTHIA_ADMIN_COOKIE_SECURE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _session_ttl_seconds() -> int:
    raw = os.getenv("SYNTHIA_ADMIN_SESSION_TTL_SECONDS", "").strip()
    try:
        parsed = int(raw) if raw else DEFAULT_SESSION_TTL_SECONDS
    except Exception:
        parsed = DEFAULT_SESSION_TTL_SECONDS
    return min(max(parsed, 300), 7 * 24 * 60 * 60)


def _session_secret(expected_token: str) -> str:
    return os.getenv("SYNTHIA_ADMIN_SESSION_SECRET", "") or f"admin-session:{expected_token}"


def _session_signature(payload: str, *, expected_token: str) -> str:
    secret = _session_secret(expected_token).encode("utf-8")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _build_session_cookie(*, expected_token: str) -> tuple[str, int]:
    expires_at = int(time.time()) + _session_ttl_seconds()
    nonce = secrets.token_urlsafe(18)
    payload = f"{expires_at}:{nonce}"
    sig = _session_signature(payload, expected_token=expected_token)
    return f"{payload}:{sig}", expires_at


def _is_valid_session_cookie(cookie_value: str | None, *, expected_token: str) -> bool:
    if not cookie_value:
        return False
    parts = cookie_value.split(":")
    if len(parts) != 3:
        return False
    expires_raw, nonce, sig = parts
    if not nonce:
        return False
    try:
        expires_at = int(expires_raw)
    except Exception:
        return False
    if expires_at <= int(time.time()):
        return False
    payload = f"{expires_raw}:{nonce}"
    expected_sig = _session_signature(payload, expected_token=expected_token)
    return hmac.compare_digest(sig, expected_sig)


def require_admin_token(x_admin_token: str | None, request: Request | None = None) -> None:
    expected = _admin_token_expected()
    if not expected:
        raise HTTPException(status_code=500, detail="SYNTHIA_ADMIN_TOKEN not configured")
    if x_admin_token and x_admin_token == expected:
        return
    if request is not None:
        cookie = request.cookies.get(ADMIN_SESSION_COOKIE)
        if _is_valid_session_cookie(cookie, expected_token=expected):
            return
    raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/admin/session/login")
def admin_session_login(body: AdminSessionLoginRequest, response: Response):
    expected = _admin_token_expected()
    if not expected:
        raise HTTPException(status_code=500, detail="SYNTHIA_ADMIN_TOKEN not configured")
    if not body.token or body.token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    cookie_value, expires_at = _build_session_cookie(expected_token=expected)
    max_age = max(expires_at - int(time.time()), 1)
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=cookie_value,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )
    return {"ok": True, "authenticated": True, "expires_at": expires_at}


@router.post("/admin/session/logout")
def admin_session_logout(response: Response):
    response.delete_cookie(key=ADMIN_SESSION_COOKIE, path="/")
    return {"ok": True, "authenticated": False}


@router.get("/admin/session/status")
def admin_session_status(request: Request):
    expected = _admin_token_expected()
    if not expected:
        raise HTTPException(status_code=500, detail="SYNTHIA_ADMIN_TOKEN not configured")
    cookie = request.cookies.get(ADMIN_SESSION_COOKIE)
    return {"ok": True, "authenticated": _is_valid_session_cookie(cookie, expected_token=expected)}


@router.post("/admin/reload")
def admin_reload(request: Request, x_admin_token: str | None = Header(default=None)):
    require_admin_token(x_admin_token, request)

    # Kick the updater oneshot. This survives the backend restarting.
    try:
        subprocess.run(
            ["systemctl", "--user", "start", "synthia-updater.service"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start updater: {e.stderr or e.stdout or str(e)}",
        )

    return {"started": True, "unit": "synthia-updater.service", "log": str(LOG_FILE)}


@router.get("/admin/reload/status")
def admin_reload_status(request: Request, x_admin_token: str | None = Header(default=None)):
    require_admin_token(x_admin_token, request)

    if not LOG_FILE.exists():
        return {"exists": False, "tail": ""}

    lines = LOG_FILE.read_text(errors="ignore").splitlines()
    tail = "\n".join(lines[-200:])
    return {"exists": True, "tail": tail}

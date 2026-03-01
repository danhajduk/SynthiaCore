from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.admin import require_admin_token
from .tokens import ServiceTokenKeyStore, sign_hs256


class ServiceTokenIssueRequest(BaseModel):
    sub: str = Field(..., min_length=1)
    aud: str = Field(..., min_length=1)
    scp: list[str] = Field(default_factory=list)
    exp: int = Field(..., description="Unix timestamp when token expires.")
    jti: str | None = None


def build_auth_router(key_store: ServiceTokenKeyStore) -> APIRouter:
    router = APIRouter()

    @router.post("/service-token")
    async def issue_service_token(
        body: ServiceTokenIssueRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        now = int(time.time())
        if body.exp <= now:
            raise HTTPException(status_code=400, detail="exp_must_be_in_future")

        key = await key_store.active_key()
        jti = body.jti or secrets.token_urlsafe(16)
        payload = {
            "sub": body.sub,
            "aud": body.aud,
            "scp": [str(s) for s in body.scp],
            "exp": int(body.exp),
            "jti": jti,
            "iat": now,
        }
        header = {"alg": "HS256", "typ": "JWT", "kid": str(key["kid"])}
        token = sign_hs256(header, payload, secret=str(key["secret"]))
        return {"ok": True, "token": token, "claims": payload, "kid": key["kid"]}

    @router.post("/service-token/rotate")
    async def rotate_service_token_key(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        ring = await key_store.rotate()
        return {"ok": True, "keys": [{"kid": k.get("kid"), "active": bool(k.get("active"))} for k in ring]}

    return router

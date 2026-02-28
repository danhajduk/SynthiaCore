from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, ConfigDict
from typing import Any


class AddonMeta(BaseModel):
    id: str = Field(..., description="Addon identifier. Must match addon folder name.")
    name: str
    version: str
    description: str = ""
    show_sidebar: bool = True
    capabilities: list[str] = Field(default_factory=list)
    auth_modes: list[str] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)
    ui: dict[str, Any] = Field(default_factory=dict)


class BackendAddon(BaseModel):
    # We intentionally store a FastAPI APIRouter here. Pydantic should not try to
    # generate a schema for it.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    meta: AddonMeta
    router: APIRouter


class RegisteredAddon(BaseModel):
    id: str = Field(..., description="Registered addon identifier.")
    name: str
    version: str
    base_url: str
    capabilities: list[str] = Field(default_factory=list)
    health_status: str = "unknown"
    last_seen: str | None = None
    auth_mode: str = "none"
    proxy_timeout_s: float = 10.0
    proxy_retries: int = 1
    proxy_circuit_fail_threshold: int = 3
    proxy_circuit_open_seconds: int = 30
    auth_header_name: str | None = None
    auth_header_env: str | None = None
    contract_ok: bool = False
    contract_errors: list[str] = Field(default_factory=list)

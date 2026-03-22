from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Any

from app.ui_metadata import UiMode, derive_addon_ui_metadata, normalize_ui_base_url, normalize_ui_mode


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
    platform_managed: bool = False


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
    ui_enabled: bool = False
    ui_base_url: str | None = None
    ui_mode: UiMode = "server"
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
    tls_warning: str | None = None
    contract_ok: bool = False
    contract_errors: list[str] = Field(default_factory=list)
    discovered_at: str | None = None
    updated_at: str | None = None
    last_health: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ui_base_url")
    @classmethod
    def _validate_ui_base_url(cls, value: str | None) -> str | None:
        return normalize_ui_base_url(value)

    @field_validator("ui_mode")
    @classmethod
    def _validate_ui_mode(cls, value: str) -> UiMode:
        return normalize_ui_mode(value, default="server")

    def model_post_init(self, __context: Any) -> None:
        fields_set = set(getattr(self, "model_fields_set", set()) or set())
        self.ui_enabled, self.ui_base_url, self.ui_mode = derive_addon_ui_metadata(
            base_url=self.base_url,
            ui_enabled=self.ui_enabled if "ui_enabled" in fields_set else None,
            ui_base_url=self.ui_base_url if "ui_base_url" in fields_set else None,
            ui_mode=self.ui_mode if "ui_mode" in fields_set else None,
        )

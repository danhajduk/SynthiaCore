from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StandaloneAddonRuntime(BaseModel):
    addon_id: str
    desired_state: str = "unknown"
    runtime_state: str = "unknown"
    active_version: str | None = None
    target_version: str | None = None
    container_name: str | None = None
    container_status: str | None = None
    running: bool | None = None
    restart_count: int | None = None
    started_at: str | None = None
    health_status: str = "unknown"
    health_detail: str | None = None
    published_ports: list[str] = Field(default_factory=list)
    network: str | None = None
    last_error: str | None = None


class StandaloneAddonRuntimeSnapshot(BaseModel):
    addon_id: str
    runtime: StandaloneAddonRuntime
    desired_path: str
    runtime_path: str
    desired_error: str | None = None
    runtime_error: str | None = None
    docker_error: str | None = None
    raw_desired: dict[str, Any] | None = None
    raw_runtime: dict[str, Any] | None = None

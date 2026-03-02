from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator


class SSAPDesiredValidationError(ValueError):
    code = "ssap_desired_invalid"

    def __init__(self, detail: str) -> None:
        super().__init__(f"{self.code}: {detail}")


class DesiredSignature(BaseModel):
    type: Literal["ed25519"]
    value: str


class DesiredRelease(BaseModel):
    artifact_url: str
    sha256: str
    publisher_key_id: str
    signature: DesiredSignature

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("sha256_must_be_64_lowercase_hex")
        return value


class DesiredInstallSource(BaseModel):
    type: str = "catalog"
    release: DesiredRelease


class DesiredRuntime(BaseModel):
    orchestrator: str = "docker_compose"
    project_name: str
    network: str
    ports: list[dict[str, Any]] = Field(default_factory=list)


class DesiredConfig(BaseModel):
    env: dict[str, str] = Field(default_factory=dict)


class DesiredStatePayload(BaseModel):
    ssap_version: Literal["1.0"]
    addon_id: str
    mode: Literal["standalone_service"]
    desired_state: Literal["running", "stopped"]
    channel: Literal["stable", "beta", "nightly"]
    pinned_version: str | None = None
    install_source: DesiredInstallSource
    runtime: DesiredRuntime
    config: DesiredConfig


def validate_desired_state(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return DesiredStatePayload.model_validate(payload).model_dump(mode="python")
    except ValidationError as exc:
        raise SSAPDesiredValidationError(str(exc)) from exc


def build_desired_state(
    *,
    addon_id: str,
    channel: str,
    pinned_version: str | None,
    artifact_url: str,
    sha256: str,
    publisher_key_id: str,
    signature_value: str,
    runtime_project_name: str,
    runtime_network: str,
    runtime_ports: list[dict[str, Any]] | None = None,
    config_env: dict[str, str] | None = None,
    desired_state: str = "running",
) -> dict[str, Any]:
    payload = {
        "ssap_version": "1.0",
        "addon_id": addon_id,
        "mode": "standalone_service",
        "desired_state": desired_state,
        "channel": channel,
        "pinned_version": pinned_version,
        "install_source": {
            "type": "catalog",
            "release": {
                "artifact_url": artifact_url,
                "sha256": sha256,
                "publisher_key_id": publisher_key_id,
                "signature": {
                    "type": "ed25519",
                    "value": signature_value,
                },
            },
        },
        "runtime": {
            "orchestrator": "docker_compose",
            "project_name": runtime_project_name,
            "network": runtime_network,
            "ports": list(runtime_ports or []),
        },
        "config": {
            "env": dict(config_env or {}),
        },
    }
    return validate_desired_state(payload)


def write_desired_state_atomic(path: Path, payload: dict[str, Any]) -> None:
    validated = validate_desired_state(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(validated, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)

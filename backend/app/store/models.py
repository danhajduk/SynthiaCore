from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator, model_validator

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
RELEASE_VERSION_SUFFIX_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"[A-Za-z][0-9A-Za-z]*$"
)

PermissionType = Literal[
    "filesystem.read",
    "filesystem.write",
    "network.egress",
    "network.ingress",
    "process.spawn",
    "system.metrics.read",
    "mqtt.publish",
    "mqtt.subscribe",
]
PackageProfile = Literal["embedded_addon", "standalone_service"]

PERMISSION_ALIASES: dict[str, list[str]] = {
    "network.outbound": ["network.egress"],
    "network.inbound": ["network.ingress"],
    "mqtt.client": ["mqtt.publish", "mqtt.subscribe"],
}


def _validate_semver(value: str, field_name: str) -> str:
    val = value.strip()
    if not SEMVER_RE.fullmatch(val):
        raise ValueError(f"{field_name} must be valid semver")
    return val


def _validate_release_version(value: str) -> str:
    val = value.strip()
    if SEMVER_RE.fullmatch(val) or RELEASE_VERSION_SUFFIX_RE.fullmatch(val):
        return val
    raise ValueError("version must be valid semver or semver+suffix (example: 0.1.7d)")


def _normalize_permissions(value: Any) -> Any:
    if not isinstance(value, list):
        return value

    normalized: list[str] = []
    for raw in value:
        token = str(raw).strip()
        expanded = PERMISSION_ALIASES.get(token, [token])
        for item in expanded:
            if item and item not in normalized:
                normalized.append(item)
    return normalized


class SignatureBlock(BaseModel):
    publisher_id: str = ""
    signature: str = ""


class RuntimePortDefault(BaseModel):
    host: int = Field(..., ge=1, le=65535)
    container: int = Field(..., ge=1, le=65535)
    proto: Literal["tcp", "udp"] = "tcp"
    purpose: str | None = None


class RuntimeDefaults(BaseModel):
    ports: list[RuntimePortDefault] = Field(default_factory=list)
    bind_localhost: bool = True


class DockerGroupDeclaration(BaseModel):
    name: str = Field(..., min_length=1)
    display_name: str | None = None
    description: str | None = None
    compose_override_file: str | None = None


class CompatibilitySpec(BaseModel):
    core_min_version: str = Field(..., min_length=1)
    core_max_version: str | None = Field(default=None)
    dependencies: list[str] = Field(...)
    conflicts: list[str] = Field(...)

    @field_validator("core_min_version")
    @classmethod
    def _validate_min_version(cls, value: str) -> str:
        return _validate_semver(value, "core_min_version")

    @field_validator("core_max_version")
    @classmethod
    def _validate_max_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_semver(value, "core_max_version")


class AddonManifest(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    core_min_version: str = Field(..., min_length=1)
    core_max_version: str | None = Field(default=None)
    dependencies: list[str] = Field(...)
    conflicts: list[str] = Field(...)
    publisher_id: str = Field(..., min_length=1)
    permissions: list[PermissionType] = Field(...)

    @field_validator("version", "core_min_version")
    @classmethod
    def _validate_required_semver(cls, value: str, info) -> str:
        return _validate_semver(value, info.field_name)

    @field_validator("core_max_version")
    @classmethod
    def _validate_optional_semver(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_semver(value, "core_max_version")

    @field_validator("permissions", mode="before")
    @classmethod
    def _normalize_permissions_aliases(cls, value: Any) -> Any:
        return _normalize_permissions(value)


class ReleaseManifest(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    # Deprecated top-level compatibility fields.
    # Kept as soft-compat adapter surface; nested `compatibility` is the source of truth.
    core_min_version: str = Field(..., min_length=1)
    core_max_version: str | None = Field(default=None)
    dependencies: list[str] = Field(...)
    conflicts: list[str] = Field(...)
    checksum: str = Field(..., min_length=1)
    publisher_id: str = Field(..., min_length=1)
    package_profile: PackageProfile = Field(default="embedded_addon")
    runtime_defaults: RuntimeDefaults | None = None
    docker_groups: list[DockerGroupDeclaration] = Field(default_factory=list)
    permissions: list[PermissionType] = Field(...)
    signature: SignatureBlock = Field(default_factory=SignatureBlock)
    compatibility: CompatibilitySpec = Field(...)

    @model_validator(mode="before")
    @classmethod
    def _compatibility_adapter(cls, raw):
        if not isinstance(raw, dict):
            return raw
        data = dict(raw)
        compat = data.get("compatibility")

        # Legacy payload support: synthesize nested compatibility from top-level fields.
        if compat is None:
            data["compatibility"] = {
                "core_min_version": data.get("core_min_version"),
                "core_max_version": data.get("core_max_version"),
                "dependencies": data.get("dependencies", []),
                "conflicts": data.get("conflicts", []),
            }
            compat = data["compatibility"]

        # Ensure required top-level fields still validate from nested compatibility.
        if isinstance(compat, dict):
            if "core_min_version" not in data:
                data["core_min_version"] = compat.get("core_min_version")
            if "core_max_version" not in data:
                data["core_max_version"] = compat.get("core_max_version")
            if "dependencies" not in data:
                data["dependencies"] = compat.get("dependencies", [])
            if "conflicts" not in data:
                data["conflicts"] = compat.get("conflicts", [])
        return data

    @field_validator("core_min_version")
    @classmethod
    def _validate_required_semver(cls, value: str, info) -> str:
        return _validate_semver(value, info.field_name)

    @field_validator("version")
    @classmethod
    def _validate_release_version_field(cls, value: str) -> str:
        return _validate_release_version(value)

    @field_validator("core_max_version")
    @classmethod
    def _validate_optional_semver(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_semver(value, "core_max_version")

    @field_validator("package_profile", mode="before")
    @classmethod
    def _normalize_package_profile(cls, value: Any) -> Any:
        if value is None:
            return "embedded_addon"
        normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "embedded": "embedded_addon",
            "addon": "embedded_addon",
            "standalone": "standalone_service",
            "service": "standalone_service",
        }
        return aliases.get(normalized, normalized)

    @field_validator("permissions", mode="before")
    @classmethod
    def _normalize_permissions_aliases(cls, value: Any) -> Any:
        return _normalize_permissions(value)

    @model_validator(mode="after")
    def _canonicalize_top_level_compat(self):
        # Nested compatibility remains the source of truth.
        self.core_min_version = self.compatibility.core_min_version
        self.core_max_version = self.compatibility.core_max_version
        self.dependencies = list(self.compatibility.dependencies)
        self.conflicts = list(self.compatibility.conflicts)
        return self


def build_store_models_router() -> APIRouter:
    router = APIRouter()

    @router.get("/schema")
    async def get_store_schemas():
        return {
            "ok": True,
            "schemas": {
                "AddonManifest": AddonManifest.model_json_schema(),
                "ReleaseManifest": ReleaseManifest.model_json_schema(),
                "CompatibilitySpec": CompatibilitySpec.model_json_schema(),
                "SignatureBlock": SignatureBlock.model_json_schema(),
                "RuntimePortDefault": RuntimePortDefault.model_json_schema(),
                "RuntimeDefaults": RuntimeDefaults.model_json_schema(),
                "DockerGroupDeclaration": DockerGroupDeclaration.model_json_schema(),
            },
        }

    return router

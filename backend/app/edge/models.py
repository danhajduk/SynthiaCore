from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProvisioningState(str, Enum):
    not_configured = "not_configured"
    pending = "pending"
    provisioned = "provisioned"
    degraded = "degraded"
    error = "error"


class CorePublicIdentity(BaseModel):
    core_id: str = Field(..., min_length=1)
    core_name: str = Field(..., min_length=1)
    platform_domain: str = Field(..., min_length=1)
    public_hostname: str = Field(..., min_length=1)
    public_ui_hostname: str = Field(..., min_length=1)
    public_api_hostname: str = Field(..., min_length=1)


class CloudflareSettings(BaseModel):
    enabled: bool = False
    account_id: str | None = None
    zone_id: str | None = None
    api_token_ref: str | None = None
    api_token_configured: bool = False
    tunnel_id: str | None = None
    tunnel_name: str | None = None
    tunnel_token_ref: str | None = None
    credentials_reference: str | None = None
    public_dns_record_id: str | None = None
    ui_dns_record_id: str | None = None
    api_dns_record_id: str | None = None
    managed_domain_base: str = "hexe-ai.com"
    hostname_publication_mode: Literal["core_id_managed"] = "core_id_managed"
    provisioning_state: ProvisioningState = ProvisioningState.not_configured
    last_provisioned_at: str | None = None
    last_provision_error: str | None = None
    config_version: str | None = None
    updated_at: str = Field(default_factory=utcnow_iso)


class EdgeTarget(BaseModel):
    target_type: Literal["core_ui", "core_api", "core_nodes_proxy", "core_addons_proxy", "local_service", "supervisor_runtime", "node", "frigate"]
    target_id: str
    upstream_base_url: str
    enabled: bool = True
    timeout_ms: int = 15000
    allowed_path_prefixes: list[str] = Field(default_factory=lambda: ["/"])

    @field_validator("allowed_path_prefixes")
    @classmethod
    def _normalize_prefixes(cls, value: list[str]) -> list[str]:
        items = [str(item or "").strip() for item in value]
        normalized = [item if item.startswith("/") else f"/{item}" for item in items if item]
        return normalized or ["/"]

    @field_validator("upstream_base_url")
    @classmethod
    def _normalize_upstream_base_url(cls, value: str) -> str:
        text = str(value or "").strip()
        parsed = urlsplit(text)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            normalized_path = "" if parsed.path in {"", "/"} else parsed.path
            return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, parsed.query, parsed.fragment))
        return text


class EdgePublication(BaseModel):
    publication_id: str
    hostname: str
    path_prefix: str = "/"
    enabled: bool = True
    source: Literal["core_owned", "operator_defined"] = "operator_defined"
    target: EdgeTarget
    last_validation_error: str | None = None
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)

    @field_validator("path_prefix")
    @classmethod
    def _normalize_path_prefix(cls, value: str) -> str:
        text = str(value or "").strip() or "/"
        return text if text.startswith("/") else f"/{text}"


class EdgeTunnelStatus(BaseModel):
    configured: bool = False
    runtime_state: str = "unknown"
    healthy: bool = False
    tunnel_id: str | None = None
    tunnel_name: str | None = None
    config_path: str | None = None
    last_error: str | None = None
    last_started_at: str | None = None
    updated_at: str | None = None


class EdgeProvisioningState(BaseModel):
    overall_state: ProvisioningState = ProvisioningState.not_configured
    tunnel_state: ProvisioningState = ProvisioningState.not_configured
    public_hostname_state: ProvisioningState = ProvisioningState.not_configured
    ui_hostname_state: ProvisioningState = ProvisioningState.not_configured
    api_hostname_state: ProvisioningState = ProvisioningState.not_configured
    dns_state: ProvisioningState = ProvisioningState.not_configured
    runtime_config_state: ProvisioningState = ProvisioningState.not_configured
    last_action: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    tunnel_id: str | None = None
    tunnel_name: str | None = None
    public_dns_record_id: str | None = None
    ui_dns_record_id: str | None = None
    api_dns_record_id: str | None = None


class EdgeTargetHealth(BaseModel):
    target_type: str
    target_id: str
    state: Literal["unknown", "healthy", "degraded", "unavailable"] = "unknown"
    detail: str | None = None


class EdgeStatus(BaseModel):
    public_identity: CorePublicIdentity
    cloudflare: CloudflareSettings
    tunnel: EdgeTunnelStatus
    provisioning: EdgeProvisioningState = Field(default_factory=EdgeProvisioningState)
    publications: list[EdgePublication] = Field(default_factory=list)
    target_health: list[EdgeTargetHealth] = Field(default_factory=list)
    reconcile_state: dict[str, object] = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)


class EdgePublicationCreateRequest(BaseModel):
    hostname: str
    path_prefix: str = "/"
    enabled: bool = True
    source: Literal["core_owned", "operator_defined"] = "operator_defined"
    target: EdgeTarget


class EdgePublicationUpdateRequest(BaseModel):
    hostname: str | None = None
    path_prefix: str | None = None
    enabled: bool | None = None
    source: Literal["core_owned", "operator_defined"] | None = None
    target: EdgeTarget | None = None


class EdgeDryRunResult(BaseModel):
    ok: bool
    public_identity: CorePublicIdentity
    validation_errors: list[str] = Field(default_factory=list)
    rendered_config: dict[str, object] = Field(default_factory=dict)
    tunnel_name: str | None = None
    dns_target: str | None = None


class CloudflareTunnelResult(BaseModel):
    tunnel_id: str
    tunnel_name: str
    tunnel_token_ref: str | None = None


class CloudflareDnsResult(BaseModel):
    hostname: str
    dns_record_id: str | None = None
    content: str
    proxied: bool = True


class CloudflareProvisionResult(BaseModel):
    ok: bool
    public_identity: CorePublicIdentity
    settings: CloudflareSettings
    provisioning: EdgeProvisioningState
    tunnel: CloudflareTunnelResult | None = None
    dns_records: list[CloudflareDnsResult] = Field(default_factory=list)
    rendered_config: dict[str, object] = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


MQTT_SETUP_STATES = Literal["unconfigured", "configuring", "ready", "error", "degraded"]
MQTT_ACCESS_MODES = Literal["gateway", "direct", "both"]
MQTT_GRANT_STATUSES = Literal["approved", "active", "provisioned", "revoked", "error"]
MQTT_HA_DISCOVERY_MODES = Literal["disabled", "gateway_managed", "addon_managed"]
MQTT_PRINCIPAL_TYPES = Literal["synthia_addon", "synthia_node", "generic_user"]
MQTT_PRINCIPAL_STATUSES = Literal["pending", "active", "probation", "revoked", "expired"]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MqttCapabilityFlags(BaseModel):
    events: bool = False
    state: bool = False
    commands: bool = False
    ha_discovery: MQTT_HA_DISCOVERY_MODES = "disabled"


class MqttRegistrationRequest(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    addon_id: str = Field(..., min_length=1)
    access_mode: MQTT_ACCESS_MODES = "gateway"
    publish_topics: list[str] = Field(default_factory=list)
    subscribe_topics: list[str] = Field(default_factory=list)
    capabilities: MqttCapabilityFlags = Field(default_factory=MqttCapabilityFlags)


class MqttRegistrationApprovalResult(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    addon_id: str = Field(..., min_length=1)
    status: Literal["approved", "rejected"] = "approved"
    access_mode: MQTT_ACCESS_MODES = "gateway"
    approved_publish_topics: list[str] = Field(default_factory=list)
    approved_subscribe_topics: list[str] = Field(default_factory=list)
    reason: str | None = None


class MqttAddonGrant(BaseModel):
    addon_id: str = Field(..., min_length=1)
    access_mode: MQTT_ACCESS_MODES = "gateway"
    status: MQTT_GRANT_STATUSES = "approved"
    publish_topics: list[str] = Field(default_factory=list)
    subscribe_topics: list[str] = Field(default_factory=list)
    granted_ha_mode: str = "disabled"
    access_profile: str = "gateway"
    provision_contract: dict[str, object] = Field(default_factory=dict)
    last_error: str | None = None
    revocation_pending: bool = False
    last_provisioned_at: str | None = None
    last_revoked_at: str | None = None
    updated_at: str = Field(default_factory=_utcnow_iso)


class MqttPrincipal(BaseModel):
    principal_id: str = Field(..., min_length=1)
    principal_type: MQTT_PRINCIPAL_TYPES = "synthia_addon"
    status: MQTT_PRINCIPAL_STATUSES = "pending"
    logical_identity: str = Field(..., min_length=1)
    linked_addon_id: str | None = None
    linked_node_id: str | None = None
    username: str | None = None
    notes: str | None = None
    last_activated_at: str | None = None
    last_revoked_at: str | None = None
    expires_at: str | None = None
    updated_at: str = Field(default_factory=_utcnow_iso)


class MqttIntegrationState(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    mqtt_enabled: bool = True
    requires_setup: bool = True
    setup_complete: bool = False
    setup_status: MQTT_SETUP_STATES = "unconfigured"
    broker_mode: str = "local"
    direct_mqtt_supported: bool = False
    setup_error: str | None = None
    authority_mode: str = "embedded_platform"
    authority_ready: bool = False
    active_grants: dict[str, MqttAddonGrant] = Field(default_factory=dict)
    principals: dict[str, MqttPrincipal] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=_utcnow_iso)


class MqttBrokerModeSummary(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    broker_mode: str = "local"
    direct_mqtt_supported: bool = False


class MqttSetupCapabilitySummary(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    requires_setup: bool = True
    setup_complete: bool = False
    setup_status: MQTT_SETUP_STATES = "unconfigured"
    direct_mqtt_supported: bool = False
    setup_error: str | None = None
    authority_mode: str = "embedded_platform"
    authority_ready: bool = False
    runtime_ready: bool = False
    setup_ready: bool = False


class MqttSetupStateUpdate(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    requires_setup: bool = True
    setup_complete: bool = False
    setup_status: MQTT_SETUP_STATES = "unconfigured"
    broker_mode: str = "local"
    direct_mqtt_supported: bool = False
    setup_error: str | None = None
    authority_mode: str = "embedded_platform"
    authority_ready: bool = False

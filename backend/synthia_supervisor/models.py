
from pydantic import BaseModel, Field
from typing import Optional


class DesiredSignature(BaseModel):
    type: str = "none"
    value: str = ""


class DesiredRelease(BaseModel):
    artifact_url: str
    sha256: str = ""
    publisher_key_id: str = ""
    signature: DesiredSignature = Field(default_factory=DesiredSignature)


class DesiredInstallSource(BaseModel):
    type: str
    release: DesiredRelease


class DesiredRuntime(BaseModel):
    project_name: str
    network: str = "synthia_net"
    ports: list[dict] = Field(default_factory=list)
    bind_localhost: bool = True
    cpu: float | None = Field(default=None, gt=0)
    memory: str | None = None


class DesiredConfig(BaseModel):
    env: dict[str, str] = Field(default_factory=dict)


class DesiredState(BaseModel):
    ssap_version: str
    addon_id: str
    desired_state: str
    desired_revision: Optional[str] = None
    pinned_version: Optional[str] = None
    install_source: DesiredInstallSource
    runtime: DesiredRuntime
    config: DesiredConfig = Field(default_factory=DesiredConfig)

class RuntimeState(BaseModel):
    ssap_version: str = "1.0"
    addon_id: str
    active_version: Optional[str] = None
    state: str
    error: Optional[str] = None
    previous_version: Optional[str] = None
    rollback_available: bool = False
    last_error: Optional[str] = None
    last_applied_desired_revision: Optional[str] = None
    last_applied_compose_digest: Optional[str] = None

    @classmethod
    def new(cls, addon_id: str):
        return cls(addon_id=addon_id, state="installing")


class ReconcileResult(BaseModel):
    addon_id: str
    desired_state: str
    final_state: str
    active_version: Optional[str] = None
    previous_version: Optional[str] = None
    changed: bool = False
    state_transition: str = "unknown->unknown"
    error: Optional[str] = None
    compose_project_name: Optional[str] = None

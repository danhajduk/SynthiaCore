
from pydantic import BaseModel
from typing import Optional


class DesiredSignature(BaseModel):
    type: str
    value: str


class DesiredRelease(BaseModel):
    artifact_url: str
    sha256: str
    publisher_key_id: str
    signature: DesiredSignature


class DesiredInstallSource(BaseModel):
    type: str
    release: DesiredRelease


class DesiredRuntime(BaseModel):
    project_name: str


class DesiredState(BaseModel):
    ssap_version: str
    addon_id: str
    desired_state: str
    pinned_version: Optional[str] = None
    install_source: DesiredInstallSource
    runtime: DesiredRuntime

class RuntimeState(BaseModel):
    ssap_version: str = "1.0"
    addon_id: str
    active_version: Optional[str] = None
    state: str
    error: Optional[str] = None
    previous_version: Optional[str] = None
    rollback_available: bool = False
    last_error: Optional[str] = None

    @classmethod
    def new(cls, addon_id: str):
        return cls(addon_id=addon_id, state="installing")


from pydantic import BaseModel
from typing import Optional, Dict

class DesiredState(BaseModel):
    ssap_version: str
    addon_id: str
    desired_state: str
    pinned_version: Optional[str] = None
    install_source: Dict
    runtime: Dict

class RuntimeState(BaseModel):
    ssap_version: str = "1.0"
    addon_id: str
    active_version: Optional[str] = None
    state: str
    error: Optional[str] = None

    @classmethod
    def new(cls, addon_id: str):
        return cls(addon_id=addon_id, state="installing")

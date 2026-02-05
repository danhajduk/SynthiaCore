from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, ConfigDict


class AddonMeta(BaseModel):
    id: str = Field(..., description="Addon identifier. Must match addon folder name.")
    name: str
    version: str
    description: str = ""
    show_sidebar: bool = True


class BackendAddon(BaseModel):
    # We intentionally store a FastAPI APIRouter here. Pydantic should not try to
    # generate a schema for it.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    meta: AddonMeta
    router: APIRouter

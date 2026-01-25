from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

class AddonMeta(BaseModel):
    id: str = Field(..., description="Addon identifier. Must match addon folder name.")
    name: str
    version: str
    description: str = ""

class BackendAddon(BaseModel):
    meta: AddonMeta
    router: APIRouter

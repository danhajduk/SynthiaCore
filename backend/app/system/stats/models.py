# backend/app/system/stats/models.py
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class LoadAvg(BaseModel):
    load1: float
    load5: float
    load15: float


class CpuStats(BaseModel):
    percent_total: float = Field(ge=0, le=100)
    percent_per_cpu: List[float]
    cores_logical: int
    cores_physical: Optional[int] = None


class MemStats(BaseModel):
    total: int
    available: int
    used: int
    free: int
    percent: float = Field(ge=0, le=100)


class SwapStats(BaseModel):
    total: int
    used: int
    free: int
    percent: float = Field(ge=0, le=100)


class DiskUsage(BaseModel):
    total: int
    used: int
    free: int
    percent: float = Field(ge=0, le=100)


class SystemStats(BaseModel):
    hostname: str
    uptime_s: float
    load: LoadAvg
    cpu: CpuStats
    mem: MemStats
    swap: SwapStats
    disks: Dict[str, DiskUsage]  # mountpoint -> usage

# backend/app/system/scheduler/models.py
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, List

from pydantic import BaseModel, Field


class JobState(str, Enum):
    queued = "queued"
    leased = "leased"
    running = "running"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class JobPriority(str, Enum):
    high = "high"
    normal = "normal"
    low = "low"
    background = "background"


class Job(BaseModel):
    job_id: str
    type: str = "generic"
    priority: JobPriority = JobPriority.normal
    requested_units: int = 1

    state: JobState = JobState.queued
    payload: Dict[str, Any] = Field(default_factory=dict)

    idempotency_key: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    max_runtime_s: Optional[int] = None  # future cutoff if you want it

    lease_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class Lease(BaseModel):
    lease_id: str
    job_id: str
    worker_id: str

    capacity_units: int
    issued_at: datetime
    expires_at: datetime
    last_heartbeat: datetime


class SchedulerSnapshot(BaseModel):
    busy_rating: int

    total_capacity_units: int
    usable_capacity_units: int
    leased_capacity_units: int
    available_capacity_units: int

    queue_depths: Dict[str, int]
    active_leases: int


# --- API Schemas ---

class SubmitJobRequest(BaseModel):
    type: str = "generic"
    priority: JobPriority = JobPriority.normal
    requested_units: int = 1
    payload: Dict[str, Any] = Field(default_factory=dict)

    idempotency_key: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    max_runtime_s: Optional[int] = None


class SubmitJobResponse(BaseModel):
    job_id: str
    state: JobState


class RequestLeaseRequest(BaseModel):
    worker_id: str
    capabilities: List[str] = Field(default_factory=list)  # v1 unused, kept for later
    max_units: Optional[int] = None  # worker-side cap


class RequestLeaseDenied(BaseModel):
    denied: bool = True
    reason: str
    retry_after_ms: int = 1500


class RequestLeaseGranted(BaseModel):
    denied: bool = False
    lease: Lease
    job: Job


class HeartbeatRequest(BaseModel):
    worker_id: str


class HeartbeatResponse(BaseModel):
    ok: bool
    expires_at: datetime


class CompleteLeaseRequest(BaseModel):
    worker_id: str
    status: str = Field(pattern="^(completed|failed)$")
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class CompleteLeaseResponse(BaseModel):
    ok: bool

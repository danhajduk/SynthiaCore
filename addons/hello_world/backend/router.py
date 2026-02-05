#   addons/hello_world/backend/router.py
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
import uuid

from app.system.scheduler.models import Job, JobPriority, JobState

router = APIRouter()


class EnqueueJobRequest(BaseModel):
    job_type: str = Field(default="helloworld.sleep")
    priority: JobPriority = Field(default=JobPriority.normal)
    requested_units: int = Field(default=5, ge=1)
    unique: bool = Field(default=False)
    payload: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None


EnqueueJobRequest.model_rebuild()


@router.post("/jobs/enqueue")
async def enqueue_job(req: Request, body: EnqueueJobRequest):
    engine = getattr(req.app.state, "scheduler_engine", None)
    if engine is None:
        return {"ok": False, "error": "scheduler_engine not available on app.state"}

    now = engine.utcnow()
    job = Job(
        job_id=str(uuid.uuid4()),
        type=body.job_type,
        priority=body.priority,
        requested_units=body.requested_units,
        unique=body.unique,
        payload=body.payload,
        idempotency_key=body.idempotency_key,
        tags=["addon:helloworld"],
        state=JobState.queued,
        created_at=now,
        updated_at=now,
    )

    job = await engine.submit_job(job)
    return {"ok": True, "job_id": job.job_id, "state": job.state}


@router.post("/jobs/burst")
async def burst(req: Request, n: int = 10, seconds: float = 1.0, units: int = 5, unique: bool = False):
    """
    Enqueue N sleep jobs (default 10), each sleeps `seconds` and requests `units`.
    """
    engine = getattr(req.app.state, "scheduler_engine", None)
    if engine is None:
        return {"ok": False, "error": "scheduler_engine not available on app.state"}

    n = max(1, min(500, int(n)))
    seconds = float(seconds)
    units = max(1, int(units))

    now = engine.utcnow()
    job_ids = []
    for _ in range(n):
        job = Job(
            job_id=str(uuid.uuid4()),
            type="helloworld.sleep",
            priority=JobPriority.normal,
            requested_units=units,
            unique=unique,
            payload={"seconds": seconds},
            tags=["addon:helloworld"],
            state=JobState.queued,
            created_at=now,
            updated_at=now,
        )
        job = await engine.submit_job(job)
        job_ids.append(job.job_id)

    return {"ok": True, "enqueued": n, "job_ids": job_ids}

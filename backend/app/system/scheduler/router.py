# backend/app/system/scheduler/router.py
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .engine import SchedulerEngine
from .models import (
    SubmitJobRequest,
    SubmitJobResponse,
    Job,
    RequestLeaseRequest,
    RequestLeaseDenied,
    RequestLeaseGranted,
    HeartbeatRequest,
    HeartbeatResponse,
    CompleteLeaseRequest,
    CompleteLeaseResponse,
    JobState,
)
from .store import SchedulerStore

router = APIRouter()

store = SchedulerStore()
engine = SchedulerEngine(store=store)

_expire_task: asyncio.Task | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.on_event("startup")
async def _startup() -> None:
    global _expire_task
    async def loop() -> None:
        while True:
            try:
                await engine.expire_tick()
            except Exception:
                # don't die because of one bad tick
                pass
            await asyncio.sleep(2.0)

    _expire_task = asyncio.create_task(loop())


@router.on_event("shutdown")
async def _shutdown() -> None:
    global _expire_task
    if _expire_task:
        _expire_task.cancel()
        _expire_task = None


@router.post("/jobs", response_model=SubmitJobResponse)
async def submit_job(req: SubmitJobRequest) -> SubmitJobResponse:
    now = utcnow()
    job = Job(
        job_id=str(uuid.uuid4()),
        type=req.type,
        priority=req.priority,
        requested_units=req.requested_units,
        payload=req.payload,
        idempotency_key=req.idempotency_key,
        tags=req.tags,
        max_runtime_s=req.max_runtime_s,
        state=JobState.queued,
        created_at=now,
        updated_at=now,
    )
    job = await engine.submit_job(job)
    return SubmitJobResponse(job_id=job.job_id, state=job.state)


@router.post("/leases/request", response_model=RequestLeaseGranted | RequestLeaseDenied)
async def request_lease(req: RequestLeaseRequest):
    out = await engine.request_lease(worker_id=req.worker_id, max_units=req.max_units)
    if isinstance(out, RequestLeaseDenied):
        return out
    lease, job = out
    return RequestLeaseGranted(lease=lease, job=job)


@router.post("/leases/{lease_id}/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(lease_id: str, req: HeartbeatRequest) -> HeartbeatResponse:
    try:
        lease = await engine.heartbeat(lease_id=lease_id, worker_id=req.worker_id)
        return HeartbeatResponse(ok=True, expires_at=lease.expires_at)
    except KeyError:
        raise HTTPException(status_code=404, detail="lease_not_found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="worker_mismatch")


@router.post("/leases/{lease_id}/complete", response_model=CompleteLeaseResponse)
async def complete(lease_id: str, req: CompleteLeaseRequest) -> CompleteLeaseResponse:
    try:
        await engine.complete(lease_id=lease_id, worker_id=req.worker_id, status=req.status)
        return CompleteLeaseResponse(ok=True)
    except PermissionError:
        raise HTTPException(status_code=403, detail="worker_mismatch")


@router.get("/status")
async def status():
    snap = await engine.snapshot()
    return JSONResponse(snap.model_dump())

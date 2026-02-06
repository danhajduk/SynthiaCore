#   addons/hello_world/backend/router.py
from __future__ import annotations

import asyncio
import time
import contextlib
from dataclasses import dataclass
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
import uuid

from app.system.scheduler.models import Job, JobPriority, JobState
from app.system.scheduler.engine import SchedulerEngine
from app.system.scheduler.models import RequestLeaseDenied
from app.system.worker.registry import HANDLERS, handler_cpu

router = APIRouter()


class EnqueueJobRequest(BaseModel):
    job_type: str = Field(default="helloworld.sleep")
    priority: JobPriority = Field(default=JobPriority.normal)
    requested_units: int = Field(default=5, ge=1)
    unique: bool = Field(default=False)
    payload: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None


EnqueueJobRequest.model_rebuild()


class StartWorkerRequest(BaseModel):
    worker_id: str = Field(default="hello-world-worker")
    max_units: Optional[int] = None
    heartbeat_interval_s: float = Field(default=5.0, ge=0.5)


StartWorkerRequest.model_rebuild()


class WorkerState:
    def __init__(self) -> None:
        self.running: bool = False
        self.worker_id: str = "hello-world-worker"
        self.max_units: Optional[int] = None
        self.heartbeat_interval_s: float = 5.0
        self.task: asyncio.Task | None = None


async def _heartbeat_loop(engine: SchedulerEngine, lease_id: str, worker_id: str, interval_s: float) -> None:
    try:
        while True:
            await asyncio.sleep(max(0.5, interval_s))
            await engine.heartbeat(lease_id=lease_id, worker_id=worker_id)
    except asyncio.CancelledError:
        return
    except Exception:
        return


async def _run_worker(engine: SchedulerEngine, state: WorkerState) -> None:
    while state.running:
        res = await engine.request_lease(worker_id=state.worker_id, max_units=state.max_units)
        if isinstance(res, RequestLeaseDenied):
            retry_ms = int(getattr(res, "retry_after_ms", 1500))
            await asyncio.sleep(max(0.25, retry_ms / 1000.0))
            continue

        lease, job = res
        hb_task = asyncio.create_task(
            _heartbeat_loop(engine, lease.lease_id, state.worker_id, state.heartbeat_interval_s)
        )
        try:
            # Simulate setup time before work begins.
            await asyncio.sleep(2.0)
            handler = HANDLERS.get(job.type)
            if handler is None:
                raise RuntimeError(f"No handler registered for job type '{job.type}'")
            # Simulate CPU load whenever a lease is granted.
            if job.type not in ("helloworld.cpu", "cpu"):
                payload = job.payload or {}
                units = max(1, int(getattr(job, "requested_units", 1) or 1))
                job_seconds = float(payload.get("seconds", 1.0))
                target_util = min(1.0, units / 25.0)  # 10 units -> 0.4 core (10% on 4 cores)
                cpu_seconds = float(payload.get("cpu_seconds", job_seconds * target_util))
                cpu_threads = int(payload.get("cpu_threads", max(1, min(16, units))))
                cpu_intensity = int(payload.get("cpu_intensity", 50000))
                if cpu_seconds > 0:
                    await handler_cpu(
                        {"seconds": cpu_seconds, "threads": cpu_threads, "intensity": cpu_intensity}
                    )
            t0 = time.time()
            await handler(job.payload or {})
            _ = time.time() - t0
            await engine.complete(lease_id=lease.lease_id, worker_id=state.worker_id, status="completed")
        except Exception:
            await engine.complete(lease_id=lease.lease_id, worker_id=state.worker_id, status="failed")
        finally:
            hb_task.cancel()
            with contextlib.suppress(Exception):
                await hb_task

    state.running = False
    state.task = None


def _get_worker_state(req: Request) -> WorkerState:
    state = getattr(req.app.state, "hello_world_worker", None)
    if state is None:
        state = WorkerState()
        req.app.state.hello_world_worker = state
    return state


@router.get("/worker/status")
async def worker_status(req: Request):
    state = _get_worker_state(req)
    return {
        "ok": True,
        "running": state.running,
        "worker_id": state.worker_id,
        "max_units": state.max_units,
        "heartbeat_interval_s": state.heartbeat_interval_s,
    }


@router.post("/worker/start")
async def worker_start(req: Request, body: StartWorkerRequest):
    engine = getattr(req.app.state, "scheduler_engine", None)
    if engine is None:
        return {"ok": False, "error": "scheduler_engine not available on app.state"}
    state = _get_worker_state(req)
    if state.running:
        return {"ok": True, "running": True}
    state.running = True
    state.worker_id = body.worker_id
    state.max_units = body.max_units
    state.heartbeat_interval_s = body.heartbeat_interval_s
    state.task = asyncio.create_task(_run_worker(engine, state))
    return {"ok": True, "running": True}


@router.post("/worker/stop")
async def worker_stop(req: Request):
    state = _get_worker_state(req)
    state.running = False
    if state.task:
        state.task.cancel()
        state.task = None
    return {"ok": True, "running": False}


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

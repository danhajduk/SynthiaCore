# backend/app/system/scheduler/router.py
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .engine import SchedulerEngine
from .queue_store import QueueStore
from .models import (
    SubmitJobRequest, SubmitJobResponse, Job,
    RequestLeaseRequest, RequestLeaseDenied, RequestLeaseGranted,
    HeartbeatRequest, HeartbeatResponse,
    CompleteLeaseRequest, CompleteLeaseResponse,
    JobIntent, QueueJobState, JobPriority,
    SubmitJobIntentRequest, SubmitJobIntentResponse,
    CancelJobIntentResponse,
    AckJobIntentRequest, AckJobIntentResponse,
    CompleteJobIntentRequest, CompleteJobIntentResponse,
    ReportLeaseRequest, ReportLeaseResponse,
    RevokeLeaseRequest, RevokeLeaseResponse,
    JobState,
)

def build_scheduler_router(engine: SchedulerEngine) -> APIRouter:
    router = APIRouter()
    expire_task: asyncio.Task | None = None
    dispatch_task: asyncio.Task | None = None
    queue_store = QueueStore()

    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @router.on_event("startup")
    async def _startup() -> None:
        nonlocal expire_task
        nonlocal dispatch_task

        async def loop() -> None:
            while True:
                try:
                    await engine.expire_tick()
                except Exception:
                    pass
                await asyncio.sleep(2.0)

        expire_task = asyncio.create_task(loop())

        async def dispatch_loop() -> None:
            while True:
                try:
                    await _dispatch_tick()
                except Exception:
                    pass
                await asyncio.sleep(2.0)

        dispatch_task = asyncio.create_task(dispatch_loop())

    @router.on_event("shutdown")
    async def _shutdown() -> None:
        nonlocal expire_task
        nonlocal dispatch_task
        if expire_task:
            expire_task.cancel()
            expire_task = None
        if dispatch_task:
            dispatch_task.cancel()
            dispatch_task = None

    @router.post("/jobs", response_model=SubmitJobResponse)
    async def submit_job(req: SubmitJobRequest) -> SubmitJobResponse:
        now = engine.utcnow()
        job = Job(
            job_id=engine.new_id(),
            type=req.type,
            priority=req.priority,
            requested_units=req.requested_units,
            unique=req.unique,
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

    @router.post("/leases/{lease_id}/report", response_model=ReportLeaseResponse)
    async def report(lease_id: str, req: ReportLeaseRequest) -> ReportLeaseResponse:
        try:
            await engine.report(
                lease_id=lease_id,
                worker_id=req.worker_id,
                progress=req.progress,
                metrics=req.metrics,
                message=req.message,
            )
            return ReportLeaseResponse(ok=True)
        except KeyError:
            raise HTTPException(status_code=404, detail="lease_not_found")
        except PermissionError:
            raise HTTPException(status_code=403, detail="worker_mismatch")

    @router.post("/leases/{lease_id}/revoke", response_model=RevokeLeaseResponse)
    async def revoke(lease_id: str, req: RevokeLeaseRequest) -> RevokeLeaseResponse:
        ok = await engine.revoke(lease_id=lease_id, reason=req.reason)
        if not ok:
            raise HTTPException(status_code=404, detail="lease_not_found")
        return RevokeLeaseResponse(ok=True)

    @router.get("/status")
    async def status():
        snap = await engine.snapshot()
        data = snap.model_dump()
        data["debug_store_id"] = hex(id(engine.store))
        data["debug_jobs_len"] = len(engine.store.jobs)
        data["debug_leases_len"] = len(engine.store.leases)
        return JSONResponse(data)

    @router.get("/jobs")
    async def jobs(limit: int = 200, state: JobState | None = None):
        limit = max(1, min(1000, int(limit)))
        now = engine.utcnow()

        async with engine.store.lock:
            jobs_list = list(engine.store.jobs.values())
            if state is not None:
                jobs_list = [job for job in jobs_list if job.state == state]

            jobs_list.sort(key=lambda job: job.updated_at, reverse=True)

            lease_by_job = {lease.job_id: lease for lease in engine.store.leases.values()}
            jobs_payload = []
            for job in jobs_list[:limit]:
                lease = lease_by_job.get(job.job_id)
                jobs_payload.append({
                    "job": job.model_dump(mode="json"),
                    "lease": lease.model_dump(mode="json") if lease else None,
                    "in_queue": job.job_id in engine.store.queued_ids,
                    "age_s": (now - job.created_at).total_seconds(),
                    "since_update_s": (now - job.updated_at).total_seconds(),
                })

            store_id = hex(id(engine.store))
            jobs_len = len(engine.store.jobs)
            leases_len = len(engine.store.leases)
            queue_depths = engine.store.queue_depths()

        snap = await engine.snapshot()

        return {
            "now": now.isoformat(),
            "store_id": store_id,
            "jobs_len": jobs_len,
            "leases_len": leases_len,
            "queue_depths": queue_depths,
            "snapshot": snap.model_dump(mode="json"),
            "jobs": jobs_payload,
        }

    @router.get("/debug/queue")
    async def debug_queue(n: int = 20):
        n = max(1, min(200, int(n)))
        q = list(engine.store.queues.normal)[:n]
        sample = []
        for jid in q:
            job = engine.store.jobs.get(jid)
            sample.append({
                "job_id": jid,
                "in_jobs": job is not None,
                "state": job.state if job else None,
                "type": job.type if job else None,
            })
        return {
            "store_id": hex(id(engine.store)),
            "jobs_len": len(engine.store.jobs),
            "queued_ids_len": getattr(engine.store, "queued_ids", None) and len(engine.store.queued_ids),
            "queue_depths": engine.store.queue_depths(),
            "sample": sample,
        }

    @router.get("/history/stats")
    async def history_stats(days: int = 30):
        history = engine.history_store
        if not history:
            return {"ok": False, "error": "history_disabled"}
        stats = await history.stats(days=days)
        return {
            "ok": True,
            "range": {
                "from": stats.range_start.isoformat(),
                "to": stats.range_end.isoformat(),
                "days": int(days),
            },
            "total": stats.total,
            "totals_by_state": stats.totals_by_state,
            "success_rate": stats.success_rate,
            "avg_queue_wait_s": stats.avg_queue_wait_s,
            "addons": stats.addons,
        }

    @router.post("/history/cleanup")
    async def history_cleanup(days: int = 30):
        history = engine.history_store
        if not history:
            return {"ok": False, "error": "history_disabled"}
        deleted = await history.cleanup(days=days)
        return {"ok": True, "deleted": deleted, "days": int(days)}

    @router.get("/history/decisions")
    async def history_decisions(days: int = 30):
        history = engine.history_store
        if not history:
            return {"ok": False, "error": "history_disabled"}
        summary = await history.decision_summary(days=days)
        return {"ok": True, **summary}

    # --------------------
    # Queueing (Job Intents)
    # --------------------

    async def _dispatch_tick() -> None:
        async with queue_store.lock:
            now = _utcnow()

            # Requeue stuck dispatching jobs
            for job in queue_store.jobs.values():
                if job.state == QueueJobState.DISPATCHING:
                    if (now - job.updated_at) > timedelta(seconds=30):
                        queue_store.reserved_units = max(0, queue_store.reserved_units - job.cost_units)
                        job.state = QueueJobState.QUEUED
                        job.updated_at = now
                        queue_store.enqueue(job)
                        queue_store.record_event(job.job_id, QueueJobState.DISPATCHING, QueueJobState.QUEUED, "dispatch_timeout")

            busy = engine.compute_busy_rating()
            usable = engine.usable_capacity_units(busy)
            leased = engine.leased_capacity_units()
            available = max(0, usable - leased - queue_store.reserved_units)

            scanned = 0
            max_scan = sum(queue_store.queue_depths().values())
            while scanned < max_scan:
                jid = queue_store.dequeue_next()
                if not jid:
                    break
                job = queue_store.jobs.get(jid)
                scanned += 1
                if not job or job.state != QueueJobState.QUEUED:
                    continue

                if job.earliest_start_at and now < job.earliest_start_at:
                    queue_store.enqueue(job)
                    continue
                if job.next_earliest_start_at and now < job.next_earliest_start_at:
                    queue_store.enqueue(job)
                    continue

                # Simple admission gate based on busy rating
                if busy >= 8 and job.priority != JobPriority.high:
                    job.attempts += 1
                    job.next_earliest_start_at = now + timedelta(seconds=5)
                    queue_store.enqueue(job)
                    continue

                if job.cost_units > available:
                    job.attempts += 1
                    job.next_earliest_start_at = now + timedelta(seconds=5)
                    queue_store.enqueue(job)
                    break

                queue_store.reserved_units += job.cost_units
                job.state = QueueJobState.DISPATCHING
                job.updated_at = now
                queue_store.record_event(job.job_id, QueueJobState.QUEUED, QueueJobState.DISPATCHING, "admitted")
                available = max(0, available - job.cost_units)

    @router.post("/queue/jobs/submit", response_model=SubmitJobIntentResponse)
    async def submit_job_intent(req: SubmitJobIntentRequest) -> SubmitJobIntentResponse:
        now = _utcnow()
        job = JobIntent(
            job_id=str(uuid.uuid4()),
            addon_id=req.addon_id,
            job_type=req.job_type,
            cost_units=req.cost_units,
            priority=req.priority,
            constraints=req.constraints,
            expected_duration_sec=req.expected_duration_sec,
            payload=req.payload,
            time_sensitive=req.time_sensitive,
            earliest_start_at=req.earliest_start_at,
            deadline_at=req.deadline_at,
            max_runtime_sec=req.max_runtime_sec,
            tags=req.tags,
            state=QueueJobState.QUEUED,
            attempts=0,
            next_earliest_start_at=None,
            lease_id=None,
            created_at=now,
            updated_at=now,
        )

        async with queue_store.lock:
            queue_store.jobs[job.job_id] = job
            queue_store.enqueue(job)
            queue_store.record_event(job.job_id, QueueJobState.QUEUED, QueueJobState.QUEUED, "submitted")

        return SubmitJobIntentResponse(job_id=job.job_id, state=job.state)

    @router.get("/queue/jobs/{job_id}")
    async def get_job_intent(job_id: str):
        async with queue_store.lock:
            job = queue_store.jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job_not_found")
            return job.model_dump(mode="json")

    @router.get("/queue/jobs")
    async def list_job_intents(state: QueueJobState | None = None, limit: int = 200):
        limit = max(1, min(1000, int(limit)))
        async with queue_store.lock:
            jobs_list = list(queue_store.jobs.values())
            if state is not None:
                jobs_list = [j for j in jobs_list if j.state == state]
            jobs_list.sort(key=lambda j: j.updated_at, reverse=True)
            return {
                "jobs_len": len(queue_store.jobs),
                "queue_depths": queue_store.queue_depths(),
                "reserved_units": queue_store.reserved_units,
                "jobs": [j.model_dump(mode="json") for j in jobs_list[:limit]],
            }

    @router.get("/queue/dispatchable")
    async def list_dispatchable(limit: int = 200):
        limit = max(1, min(1000, int(limit)))
        async with queue_store.lock:
            jobs_list = [j for j in queue_store.jobs.values() if j.state == QueueJobState.DISPATCHING]
            jobs_list.sort(key=lambda j: j.updated_at, reverse=False)
            return {"jobs": [j.model_dump(mode="json") for j in jobs_list[:limit]]}

    @router.post("/queue/jobs/{job_id}/cancel", response_model=CancelJobIntentResponse)
    async def cancel_job_intent(job_id: str) -> CancelJobIntentResponse:
        async with queue_store.lock:
            job = queue_store.jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job_not_found")
            if job.state in (QueueJobState.DONE, QueueJobState.FAILED, QueueJobState.CANCELED):
                return CancelJobIntentResponse(ok=True)

            prev = job.state
            if job.state == QueueJobState.DISPATCHING:
                queue_store.reserved_units = max(0, queue_store.reserved_units - job.cost_units)
            job.state = QueueJobState.CANCELED
            job.updated_at = _utcnow()
            queue_store.record_event(job.job_id, prev, QueueJobState.CANCELED, "canceled")
            return CancelJobIntentResponse(ok=True)

    @router.post("/queue/jobs/{job_id}/ack", response_model=AckJobIntentResponse)
    async def ack_job_intent(job_id: str, req: AckJobIntentRequest) -> AckJobIntentResponse:
        async with queue_store.lock:
            job = queue_store.jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job_not_found")
            if job.state != QueueJobState.DISPATCHING:
                raise HTTPException(status_code=409, detail="job_not_dispatching")
            queue_store.reserved_units = max(0, queue_store.reserved_units - job.cost_units)
            prev = job.state
            job.state = QueueJobState.RUNNING
            job.lease_id = req.lease_id
            job.updated_at = _utcnow()
            queue_store.record_event(job.job_id, prev, QueueJobState.RUNNING, "ack")
            return AckJobIntentResponse(ok=True)

    @router.post("/queue/jobs/{job_id}/complete", response_model=CompleteJobIntentResponse)
    async def complete_job_intent(job_id: str, req: CompleteJobIntentRequest) -> CompleteJobIntentResponse:
        async with queue_store.lock:
            job = queue_store.jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job_not_found")
            prev = job.state
            if req.status == "DONE":
                job.state = QueueJobState.DONE
            else:
                job.state = QueueJobState.FAILED
            job.updated_at = _utcnow()
            queue_store.record_event(job.job_id, prev, job.state, "complete")
            return CompleteJobIntentResponse(ok=True)

    return router

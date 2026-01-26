# backend/app/system/scheduler/engine.py
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Union

from .models import (
    Job,
    Lease,
    JobState,
    SchedulerSnapshot,
    RequestLeaseDenied,
)
from .store import SchedulerStore


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SchedulerEngine:
    """
    Core scheduling logic. Conservative and deterministic.
    """

    # Busy->usable % curve (fail-closed friendly)
    BUSY_TO_PERCENT = {
        0: 1.00,
        1: 1.00,
        2: 1.00,
        3: 0.80,
        4: 0.65,
        5: 0.50,
        6: 0.35,
        7: 0.25,
        8: 0.15,
        9: 0.10,
        10: 0.00,
    }

    def __init__(
        self,
        store: SchedulerStore,
        total_capacity_units: int = 100,
        reserve_units: int = 5,
        lease_ttl_s: int = 60,
        heartbeat_grace_s: int = 0,
        failclosed_busy_default: int = 8,
    ) -> None:
        self.store = store
        self.total_capacity_units = total_capacity_units
        self.reserve_units = reserve_units
        self.lease_ttl_s = lease_ttl_s
        self.heartbeat_grace_s = heartbeat_grace_s

        # env override
        self.failclosed_busy_default = int(
            os.getenv("SCHEDULER_FAILCLOSED_BUSY", str(failclosed_busy_default))
        )

    # ---------- Busy rating (stub for now) ----------
    def compute_busy_rating(self) -> int:
        """
        v1: fail-closed if we don't have real metrics yet.
        Later: pull from your stats collector (CPU/mem/latency/inflight/errors).
        """
        return self.failclosed_busy_default

    # ---------- Capacity ----------
    def usable_capacity_units(self, busy: int) -> int:
        busy = max(0, min(10, busy))
        percent = self.BUSY_TO_PERCENT[busy]
        usable = int(self.total_capacity_units * percent) - self.reserve_units
        return max(0, usable)

    def leased_capacity_units(self) -> int:
        return sum(l.capacity_units for l in self.store.leases.values())

    # ---------- Snapshot ----------
    async def snapshot(self) -> SchedulerSnapshot:
        async with self.store.lock:
            busy = self.compute_busy_rating()
            usable = self.usable_capacity_units(busy)
            leased = self.leased_capacity_units()
            available = max(0, usable - leased)

            return SchedulerSnapshot(
                busy_rating=busy,
                total_capacity_units=self.total_capacity_units,
                usable_capacity_units=usable,
                leased_capacity_units=leased,
                available_capacity_units=available,
                queue_depths=self.store.queue_depths(),
                active_leases=len(self.store.leases),
            )

    # ---------- Job submit ----------
    async def submit_job(self, job: Job) -> Job:
        async with self.store.lock:
            if job.idempotency_key:
                existing = self.store.idempotency_index.get(job.idempotency_key)
                if existing and existing in self.store.jobs:
                    return self.store.jobs[existing]

            self.store.jobs[job.job_id] = job
            if job.idempotency_key:
                self.store.idempotency_index[job.idempotency_key] = job.job_id
            self.store.enqueue(job)
            return job

    # ---------- Lease request (pull model) ----------
    async def request_lease(
        self,
        worker_id: str,
        max_units: Optional[int] = None,
    ) -> Union[Tuple[Lease, Job], RequestLeaseDenied]:
        async with self.store.lock:
            # expire first, so capacity is accurate
            self._expire_leases_locked()

            busy = self.compute_busy_rating()
            usable = self.usable_capacity_units(busy)
            leased = self.leased_capacity_units()
            available = max(0, usable - leased)

            if available <= 0:
                return RequestLeaseDenied(reason=f"No capacity (busy={busy}, usable={usable}, leased={leased})")

            # Find next job that fits.
            # Conservative: if it doesn't fit, we don't do partial allocation.
            scanned = 0
            max_scan = sum(self.store.queue_depths().values())

            while scanned < max_scan:
                job_id = self.store.dequeue_next()
                if not job_id:
                    return RequestLeaseDenied(reason="No queued jobs")

                job = self.store.jobs.get(job_id)
                scanned += 1
                if not job:
                    continue

                if job.state != JobState.queued:
                    continue

                need = int(job.requested_units)
                if need <= 0:
                    job.state = JobState.failed
                    job.updated_at = utcnow()
                    continue

                if max_units is not None:
                    need = min(need, int(max_units))

                if need > available:
                    # Put it back at the end of its queue to avoid head-of-line blocking.
                    # Still strict: we won't run it until enough capacity exists.
                    self.store.enqueue(job)
                    return RequestLeaseDenied(
                        reason=f"Next job needs {job.requested_units}u but only {available}u available",
                        retry_after_ms=2000,
                    )

                # grant lease
                lease_id = str(uuid.uuid4())
                now = utcnow()
                expires = now + timedelta(seconds=self.lease_ttl_s + self.heartbeat_grace_s)

                lease = Lease(
                    lease_id=lease_id,
                    job_id=job.job_id,
                    worker_id=worker_id,
                    capacity_units=need,
                    issued_at=now,
                    expires_at=expires,
                    last_heartbeat=now,
                )

                job.state = JobState.leased
                job.lease_id = lease_id
                job.updated_at = now

                self.store.leases[lease_id] = lease
                return lease, job

            return RequestLeaseDenied(reason="No eligible job found")

    # ---------- Heartbeat ----------
    async def heartbeat(self, lease_id: str, worker_id: str) -> Lease:
        async with self.store.lock:
            self._expire_leases_locked()

            lease = self.store.leases.get(lease_id)
            if not lease:
                raise KeyError("lease_not_found")

            if lease.worker_id != worker_id:
                raise PermissionError("worker_mismatch")

            now = utcnow()
            lease.last_heartbeat = now
            lease.expires_at = now + timedelta(seconds=self.lease_ttl_s + self.heartbeat_grace_s)

            job = self.store.jobs.get(lease.job_id)
            if job and job.state in (JobState.leased, JobState.running):
                # first heartbeat = imply running (worker started)
                if job.state == JobState.leased:
                    job.state = JobState.running
                job.updated_at = now

            self.store.leases[lease_id] = lease
            return lease

    # ---------- Complete ----------
    async def complete(self, lease_id: str, worker_id: str, status: str) -> None:
        async with self.store.lock:
            self._expire_leases_locked()

            lease = self.store.leases.get(lease_id)
            if not lease:
                # idempotent-ish: if already gone, treat as ok
                return

            if lease.worker_id != worker_id:
                raise PermissionError("worker_mismatch")

            now = utcnow()
            job = self.store.jobs.get(lease.job_id)
            if job:
                if status == "completed":
                    job.state = JobState.completed
                else:
                    job.state = JobState.failed
                job.updated_at = now

            # release capacity
            self.store.leases.pop(lease_id, None)

    # ---------- Expiry loop ----------
    def _expire_leases_locked(self) -> int:
        """
        Expire leases and mark jobs expired. Must be called under store.lock.
        """
        now = utcnow()
        expired_ids = [lid for lid, l in self.store.leases.items() if l.expires_at <= now]
        for lid in expired_ids:
            lease = self.store.leases.pop(lid, None)
            if not lease:
                continue
            job = self.store.jobs.get(lease.job_id)
            if job and job.state in (JobState.leased, JobState.running):
                job.state = JobState.expired
                job.updated_at = now
                job.lease_id = None
        return len(expired_ids)

    async def expire_tick(self) -> int:
        async with self.store.lock:
            return self._expire_leases_locked()

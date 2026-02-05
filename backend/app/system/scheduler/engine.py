# backend/app/system/scheduler/engine.py
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Tuple, Union

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
        metrics_provider: Optional[Callable[[], Tuple[Any | None, Any | None]]] = None,
    ) -> None:
        self.store = store
        self.total_capacity_units = total_capacity_units
        self.reserve_units = reserve_units
        self.lease_ttl_s = lease_ttl_s
        self.heartbeat_grace_s = heartbeat_grace_s

        self.metrics_provider = metrics_provider or (lambda: (None, None))

        # env override
        self.failclosed_busy_default = int(
            os.getenv("SCHEDULER_FAILCLOSED_BUSY", str(failclosed_busy_default))
        )

    # ---------- Small helpers (router convenience) ----------
    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

    # canonical name
    @staticmethod
    def utcnow() -> datetime:
        return utcnow()

    # backwards-compatible alias (in case anything still calls engine.utcnow())
    @staticmethod
    def utcnow() -> datetime:
        return utcnow()

    # ---------- Busy rating ----------
    def compute_busy_rating(self) -> int:
        """
        v1 heuristic:
          - If metrics missing/stale: fail-closed (busy=failclosed_busy_default)
          - Otherwise compute a 0..10 score from CPU/MEM + API p95/error (when present)

        Defensive about field names until stats schema is finalized.
        """
        stats, api = self.metrics_provider()

        if stats is None and api is None:
            return self.failclosed_busy_default

        # Optional staleness check if stats carries a timestamp
        try:
            collected_at = getattr(stats, "collected_at", None) or getattr(stats, "ts", None)
            if isinstance(collected_at, datetime):
                age_s = (utcnow() - collected_at).total_seconds()
                if age_s > 30:
                    stats = None
        except Exception:
            pass

        score = 0

        cpu = self._first_number(stats, ["cpu_percent", "cpu_pct", "cpu"])
        mem = self._first_number(stats, ["mem_percent", "memory_percent", "mem_pct", "ram_percent", "ram_pct"])

        # CPU contributes up to 4
        if cpu is not None:
            if cpu >= 95:
                score += 4
            elif cpu >= 85:
                score += 3
            elif cpu >= 70:
                score += 2
            elif cpu >= 50:
                score += 1

        # MEM contributes up to 3
        if mem is not None:
            if mem >= 95:
                score += 3
            elif mem >= 85:
                score += 2
            elif mem >= 70:
                score += 1

        p95 = self._first_number(api, ["p95_ms", "latency_p95_ms", "p95", "p95_latency_ms"])
        err = self._first_number(api, ["error_rate", "errors_rate", "err_rate"])
        inflight = self._first_number(api, ["inflight", "in_flight", "active_requests"])

        # Latency contributes up to 3
        if p95 is not None:
            if p95 >= 1500:
                score += 3
            elif p95 >= 800:
                score += 2
            elif p95 >= 400:
                score += 1

        # Error rate contributes up to 3
        if err is not None:
            if err > 1.0:
                err = err / 100.0
            if err >= 0.10:
                score += 3
            elif err >= 0.03:
                score += 2
            elif err >= 0.01:
                score += 1

        # Inflight contributes up to 2 (optional)
        if inflight is not None:
            if inflight >= 100:
                score += 2
            elif inflight >= 50:
                score += 1

        return max(0, min(10, int(score)))

    @staticmethod
    def _first_number(obj: Any, fields: list[str]) -> Optional[float]:
        if obj is None:
            return None
        for f in fields:
            try:
                if isinstance(obj, dict) and f in obj:
                    v = obj.get(f)
                else:
                    v = getattr(obj, f, None)

                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, str):
                    v2 = v.strip().replace("%", "")
                    return float(v2)
            except Exception:
                continue
        return None

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

            job.state = JobState.queued
            job.lease_id = None
            job.updated_at = utcnow()

            # ✅ enqueue exactly once
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
                return RequestLeaseDenied(
                    reason=f"No capacity (busy={busy}, usable={usable}, leased={leased})"
                )

            scanned = 0
            max_scan = sum(self.store.queue_depths().values())
            worker_has_lease = any(lease.worker_id == worker_id for lease in self.store.leases.values())

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
                if job.unique and worker_has_lease:
                    self.store.enqueue(job)
                    continue

                need = int(job.requested_units)
                if need <= 0:
                    job.state = JobState.failed
                    job.updated_at = utcnow()
                    continue

                if max_units is not None:
                    need = min(need, int(max_units))

                if need > available:
                    self.store.enqueue(job)
                    return RequestLeaseDenied(
                        reason=f"Next job needs {job.requested_units}u but only {available}u available",
                        retry_after_ms=2000,
                    )

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

            return RequestLeaseDenied(
                reason=f"No eligible job found (store={hex(id(self.store))}, jobs={len(self.store.jobs)}, queues={self.store.queue_depths()})"
            )

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
                return

            if lease.worker_id != worker_id:
                raise PermissionError("worker_mismatch")

            now = utcnow()
            job = self.store.jobs.get(lease.job_id)
            if job:
                job.state = JobState.completed if status == "completed" else JobState.failed
                job.updated_at = now

            self.store.leases.pop(lease_id, None)

    # ---------- Expiry loop ----------
    def _expire_leases_locked(self) -> int:
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

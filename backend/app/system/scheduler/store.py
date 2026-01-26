# backend/app/system/scheduler/store.py
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

from .models import Job, Lease, JobPriority


@dataclass
class Queues:
    high: Deque[str]
    normal: Deque[str]
    low: Deque[str]
    background: Deque[str]


class SchedulerStore:
    """
    In-memory store. Single-process safe via asyncio.Lock.
    """
    def __init__(self) -> None:
        self.lock = asyncio.Lock()

        self.jobs: Dict[str, Job] = {}
        self.leases: Dict[str, Lease] = {}
        self.idempotency_index: Dict[str, str] = {}  # idempotency_key -> job_id

        self.queues = Queues(
            high=deque(),
            normal=deque(),
            low=deque(),
            background=deque(),
        )

        # Prevent duplicate job_ids from accumulating in queues
        self.queued_ids: set[str] = set()

    def _queue_for(self, prio: JobPriority) -> Deque[str]:
        if prio == JobPriority.high:
            return self.queues.high
        if prio == JobPriority.normal:
            return self.queues.normal
        if prio == JobPriority.low:
            return self.queues.low
        return self.queues.background

    def enqueue(self, job: Job) -> None:
        """
        Enqueue job_id once (deduped).
        """
        if job.job_id in self.queued_ids:
            return
        self.queued_ids.add(job.job_id)
        self._queue_for(job.priority).append(job.job_id)

    def dequeue_next(self) -> Optional[str]:
        """
        Strict priority order. (Fairness/aging can come later.)
        Dequeues a job_id and removes it from queued_ids.
        """
        if self.queues.high:
            jid = self.queues.high.popleft()
            self.queued_ids.discard(jid)
            return jid
        if self.queues.normal:
            jid = self.queues.normal.popleft()
            self.queued_ids.discard(jid)
            return jid
        if self.queues.low:
            jid = self.queues.low.popleft()
            self.queued_ids.discard(jid)
            return jid
        if self.queues.background:
            jid = self.queues.background.popleft()
            self.queued_ids.discard(jid)
            return jid
        return None

    def queue_depths(self) -> Dict[str, int]:
        return {
            "high": len(self.queues.high),
            "normal": len(self.queues.normal),
            "low": len(self.queues.low),
            "background": len(self.queues.background),
        }

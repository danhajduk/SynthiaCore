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

    def _queue_for(self, prio: JobPriority) -> Deque[str]:
        if prio == JobPriority.high:
            return self.queues.high
        if prio == JobPriority.normal:
            return self.queues.normal
        if prio == JobPriority.low:
            return self.queues.low
        return self.queues.background

    def dequeue_next(self) -> Optional[str]:
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

    def dequeue_next(self) -> Optional[str]:
        """
        Strict priority order. (Fairness/aging can come later.)
        """
        if self.queues.high:
            return self.queues.high.popleft()
        if self.queues.normal:
            return self.queues.normal.popleft()
        if self.queues.low:
            return self.queues.low.popleft()
        if self.queues.background:
            return self.queues.background.popleft()
        return None

    def queue_depths(self) -> Dict[str, int]:
        return {
            "high": len(self.queues.high),
            "normal": len(self.queues.normal),
            "low": len(self.queues.low),
            "background": len(self.queues.background),
        }

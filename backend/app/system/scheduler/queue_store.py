# backend/app/system/scheduler/queue_store.py
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, List, Optional

from .models import JobIntent, JobPriority, QueueJobState


@dataclass
class QueueEvent:
    ts: datetime
    job_id: str
    from_state: QueueJobState
    to_state: QueueJobState
    reason: Optional[str] = None


@dataclass
class QueueBuckets:
    high: Deque[str]
    normal: Deque[str]
    low: Deque[str]
    background: Deque[str]


class QueueStore:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.jobs: Dict[str, JobIntent] = {}
        self.queued_ids: set[str] = set()
        self.reserved_units: int = 0
        self.events: List[QueueEvent] = []

        self.queues = QueueBuckets(
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

    def enqueue(self, job: JobIntent) -> None:
        if job.job_id in self.queued_ids:
            return
        self.queued_ids.add(job.job_id)
        self._queue_for(job.priority).append(job.job_id)

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

    def queue_depths(self) -> Dict[str, int]:
        return {
            "high": len(self.queues.high),
            "normal": len(self.queues.normal),
            "low": len(self.queues.low),
            "background": len(self.queues.background),
        }

    def record_event(
        self,
        job_id: str,
        from_state: QueueJobState,
        to_state: QueueJobState,
        reason: Optional[str] = None,
    ) -> None:
        self.events.append(
            QueueEvent(
                ts=datetime.utcnow(),
                job_id=job_id,
                from_state=from_state,
                to_state=to_state,
                reason=reason,
            )
        )

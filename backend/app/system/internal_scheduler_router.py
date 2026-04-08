from __future__ import annotations

from fastapi import APIRouter, Request


def build_internal_scheduler_router() -> APIRouter:
    router = APIRouter()

    @router.get("/scheduler/internal")
    def get_internal_scheduler(request: Request) -> dict[str, object]:
        internal_scheduler = getattr(request.app.state, "internal_scheduler", None)
        if internal_scheduler is None or not hasattr(internal_scheduler, "snapshot"):
            return {"configured": False, "scheduler_status": "unavailable", "tasks": {}}
        snapshot = internal_scheduler.snapshot()
        if not isinstance(snapshot, dict):
            return {"configured": False, "scheduler_status": "unavailable", "tasks": {}}
        return {"configured": True, **snapshot}

    return router

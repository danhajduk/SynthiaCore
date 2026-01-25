# backend/app/system/stats/router.py

from fastapi import APIRouter, Request
from .models import SystemStats
from .service import collect_system_stats

router = APIRouter(tags=["system"])

@router.get("/system/stats/current", response_model=SystemStats)
def get_current_stats(request: Request):
    cached = getattr(request.app.state, "latest_stats", None)
    if cached is not None:
        return cached

    # fallback during startup
    api_metrics = getattr(request.app.state, "api_metrics", None)
    return collect_system_stats(api_metrics=api_metrics)

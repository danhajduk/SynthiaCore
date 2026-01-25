# backend/app/system/stats/router.py
from fastapi import APIRouter
from .models import SystemStats
from .service import collect_system_stats

router = APIRouter(tags=["system"])

@router.get("/stats/current", response_model=SystemStats)
def get_current_stats() -> SystemStats:
    return collect_system_stats()

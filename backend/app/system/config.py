# backend/app/system/config.py
from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel, Field


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_optional_int(name: str, default: Optional[int]) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class QuietThresholds(BaseModel):
    quiet_max: float = Field(default=2.0, ge=0, le=10)
    normal_max: float = Field(default=5.0, ge=0, le=10)
    busy_max: float = Field(default=7.0, ge=0, le=10)


class SystemConfig(BaseModel):
    # Sampling intervals
    stats_fast_interval_s: float = Field(default=5.0, ge=1.0)
    api_metrics_window_s: int = Field(default=60, ge=1)
    api_metrics_interval_s: int = Field(default=10, ge=1)

    # Retention
    stats_retention_days: int = Field(default=1, ge=1)

    # Quiet thresholds
    quiet_thresholds: QuietThresholds = QuietThresholds()

    # Scheduler limits
    scheduler_capacity_headroom_pct: float = Field(default=0.05, ge=0.0, le=1.0)
    scheduler_max_active_leases: Optional[int] = None
    scheduler_max_active_leases_per_addon: Optional[int] = None

    # Queueing
    queue_dispatch_interval_s: float = Field(default=2.0, ge=0.5)
    queue_dispatch_timeout_s: float = Field(default=30.0, ge=5.0)



def load_config() -> SystemConfig:
    quiet = QuietThresholds(
        quiet_max=_env_float("QUIET_THRESHOLD_MAX", 2.0),
        normal_max=_env_float("NORMAL_THRESHOLD_MAX", 5.0),
        busy_max=_env_float("BUSY_THRESHOLD_MAX", 7.0),
    )

    return SystemConfig(
        stats_fast_interval_s=_env_float("STATS_FAST_INTERVAL_S", 5.0),
        api_metrics_window_s=_env_int("API_METRICS_WINDOW_S", 60),
        api_metrics_interval_s=_env_int("API_METRICS_INTERVAL_S", 10),
        stats_retention_days=_env_int("STATS_RETENTION_DAYS", 1),
        quiet_thresholds=quiet,
        scheduler_capacity_headroom_pct=_env_float("SCHEDULER_CAPACITY_HEADROOM_PCT", 0.05),
        scheduler_max_active_leases=_env_optional_int("SCHEDULER_MAX_ACTIVE_LEASES", None),
        scheduler_max_active_leases_per_addon=_env_optional_int(
            "SCHEDULER_MAX_ACTIVE_LEASES_PER_ADDON",
            None,
        ),
        queue_dispatch_interval_s=_env_float("QUEUE_DISPATCH_INTERVAL_S", 2.0),
        queue_dispatch_timeout_s=_env_float("QUEUE_DISPATCH_TIMEOUT_S", 30.0),
    )

# backend/app/system/stats/router.py

import time
from fastapi import APIRouter, HTTPException, Request
from .models import SystemStats, SystemStatsSnapshot
from .service import collect_system_stats, collect_system_snapshot
from app.system.stats_store import StatsStore
from .service import compute_quiet_assessment

_stats_store = StatsStore()


def _parse_duration_s(raw: str) -> int:
    raw = raw.strip().lower()
    if raw.endswith("ms"):
        return max(1, int(float(raw[:-2]) / 1000))
    if raw.endswith("s"):
        return max(1, int(float(raw[:-1])))
    if raw.endswith("m"):
        return max(1, int(float(raw[:-1]) * 60))
    if raw.endswith("h"):
        return max(1, int(float(raw[:-1]) * 3600))
    if raw.endswith("d"):
        return max(1, int(float(raw[:-1]) * 86400))
    # default seconds if no suffix
    return max(1, int(float(raw)))

router = APIRouter(tags=["system"])

@router.get("/system/stats/current", response_model=SystemStats)
def get_current_stats(request: Request):
    cached = getattr(request.app.state, "latest_stats", None)
    if cached is not None:
        return cached

    # fallback during startup
    api_metrics = getattr(request.app.state, "api_metrics", None)
    return collect_system_stats(api_metrics=api_metrics)


@router.get("/system-stats/current", response_model=SystemStatsSnapshot)
def get_current_system_snapshot(request: Request):
    cached = getattr(request.app.state, "latest_system_snapshot", None)
    if cached is not None:
        return cached

    api_metrics = getattr(request.app.state, "api_metrics", None)
    registry = getattr(request.app.state, "addon_registry", None)
    cfg = getattr(request.app.state, "system_config", None)
    quiet_thresholds = getattr(cfg, "quiet_thresholds", None) if cfg else None
    return collect_system_snapshot(
        api_metrics=api_metrics,
        registry=registry,
        quiet_thresholds=quiet_thresholds,
    )


@router.get("/system-stats/history")
def get_system_stats_history(
    group: str = "busy",
    range: str = "1h",
    step: str = "60s",
):
    group = group.strip().lower()
    range_s = _parse_duration_s(range)
    step_s = _parse_duration_s(step)
    if step_s < 1:
        step_s = 1

    now = time.time()
    start_ts = now - range_s

    rows = _stats_store.range_points(start_ts=start_ts, end_ts=now)

    points = []
    last_ts = None
    for ts, busy in rows:
        if last_ts is not None and (ts - last_ts) < step_s:
            continue

        if group in ("busy", "busy_rating"):
            value = float(busy)
        elif group == "quiet":
            value = max(0.0, 100.0 - (float(busy) * 10.0))
        else:
            raise HTTPException(status_code=400, detail="unsupported_group")

        points.append({"ts": ts, "value": round(value, 3)})
        last_ts = ts

    return {
        "group": group,
        "range_s": range_s,
        "step_s": step_s,
        "points": points,
    }


@router.get("/system-stats/health")
def get_system_stats_health(request: Request):
    # Use the most recent minute entry if available.
    rows = _stats_store.last_n(1)
    if not rows:
        raise HTTPException(status_code=503, detail="no_stats")

    ts, busy = rows[-1]
    cfg = getattr(request.app.state, "system_config", None)
    quiet_thresholds = getattr(cfg, "quiet_thresholds", None) if cfg else None
    if quiet_thresholds is None:
        quiet = compute_quiet_assessment(busy)
    else:
        quiet = compute_quiet_assessment(
            busy,
            quiet_max=quiet_thresholds.quiet_max,
            normal_max=quiet_thresholds.normal_max,
            busy_max=quiet_thresholds.busy_max,
        )

    if quiet.state == "QUIET":
        status = "ok"
    elif quiet.state == "NORMAL":
        status = "ok"
    elif quiet.state == "BUSY":
        status = "warn"
    else:
        status = "error"

    quiet_streaks = _compute_quiet_streaks(hours=24)

    return {
        "status": status,
        "busy_rating": round(float(busy), 2),
        "quiet_score": quiet.quiet_score,
        "quiet_state": quiet.state,
        "reasons": quiet.reasons,
        "timestamp": ts,
        "quiet_streaks_24h": quiet_streaks,
    }


def _compute_quiet_streaks(hours: int = 24):
    now = time.time()
    start_ts = now - (hours * 3600)
    rows = _stats_store.range_points(start_ts=start_ts, end_ts=now)

    streaks = []
    current = None
    scores = []

    for ts, busy in rows:
        quiet = compute_quiet_assessment(busy)
        if quiet.state == "QUIET":
            if current is None:
                current = {"start_time": ts, "end_time": ts}
                scores = [quiet.quiet_score]
            else:
                current["end_time"] = ts
                scores.append(quiet.quiet_score)
        else:
            if current is not None:
                avg_score = sum(scores) / len(scores) if scores else 0
                current["avg_score"] = round(avg_score, 2)
                current["min_score"] = min(scores) if scores else 0
                streaks.append(current)
                current = None
                scores = []

    if current is not None:
        avg_score = sum(scores) / len(scores) if scores else 0
        current["avg_score"] = round(avg_score, 2)
        current["min_score"] = min(scores) if scores else 0
        streaks.append(current)

    return streaks

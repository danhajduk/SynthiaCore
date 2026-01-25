# backend/app/system/sampler.py
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI

from app.system.stats_store import StatsStore
from app.system.stats.service import collect_system_stats
from app.system.busy_rating import compute_busy_rating

log = logging.getLogger(__name__)
store = StatsStore()


def _align_to_next_minute(ts: float) -> float:
    return (int(ts // 60) + 1) * 60.0


async def stats_fast_sampler_loop(app: FastAPI, interval_s: float = 5.0) -> None:
    """
    Collect system stats every `interval_s` seconds.
    API metrics are NOT recomputed here; we use the last snapshot captured by api_metrics_sampler_loop().
    Result is stored in app.state.latest_stats (combined snapshot).
    """
    while True:
        try:
            # Collect system stats (no API snapshot computation inside service)
            sys_snap = collect_system_stats(api_metrics=None)

            # Get latest API metrics snapshot (captured every 60s)
            api_snap: Dict[str, Any] = getattr(app.state, "latest_api_metrics", None) or {}

            # Compute busy rating using system snapshot + last API snapshot
            sys_dict = sys_snap.model_dump()
            busy = compute_busy_rating(sys_dict, api_snap)

            # Build a "combined" SystemStats object (same as sys_snap but with api + busy_rating filled in)
            # Pydantic v2: model_copy(update=...)
            combined = sys_snap.model_copy(
                update={
                    "api": api_snap,
                    "busy_rating": round(float(busy), 2),
                }
            )

            app.state.latest_stats = combined

        except Exception:
            log.exception("stats_fast_sampler_loop failed; continuing")

        await asyncio.sleep(interval_s)


async def api_metrics_sampler_loop(app: FastAPI, window_s: int = 60, top_n: int = 10) -> None:
    """
    Snapshot API metrics every 60s (or whatever window_s is).
    This reads the ApiMetricsCollector that middleware is already populating.
    """
    while True:
        try:
            collector = getattr(app.state, "api_metrics", None)
            if collector is None:
                log.warning("api_metrics_sampler_loop: app.state.api_metrics is not set yet")
            else:
                app.state.latest_api_metrics = collector.snapshot(window_s=window_s, top_n=top_n)

        except Exception:
            log.exception("api_metrics_sampler_loop failed; continuing")

        await asyncio.sleep(window_s)


async def stats_minute_writer_loop(app: FastAPI) -> None:
    """
    Every minute (on the minute), store the latest combined snapshot + busy rating in SQLite.
    Keeps 24h of data.
    """
    while True:
        now = time.time()
        next_min = _align_to_next_minute(now)
        await asyncio.sleep(max(0.0, next_min - now))

        try:
            snap = getattr(app.state, "latest_stats", None)

            # If we're still booting and don't have a cached snapshot yet,
            # do a one-off collection (with API snapshot if available).
            if snap is None:
                api_snap: Dict[str, Any] = getattr(app.state, "latest_api_metrics", None) or {}
                sys_snap = collect_system_stats(api_metrics=None)
                sys_dict = sys_snap.model_dump()
                busy = compute_busy_rating(sys_dict, api_snap)
                snap = sys_snap.model_copy(
                    update={"api": api_snap, "busy_rating": round(float(busy), 2)}
                )

            snap_dict = snap.model_dump()

            # Force stored timestamp to be minute-aligned (so DB keys are stable)
            snap_dict["timestamp"] = next_min

            # Recompute busy rating at write time (cheap + ensures it matches stored api snapshot)
            api = snap_dict.get("api") or {}
            snap_dict["busy_rating"] = round(float(compute_busy_rating(snap_dict, api)), 2)

            store.insert_minute(ts=next_min, busy=float(snap_dict["busy_rating"]), snapshot=snap_dict)
            store.prune_older_than(seconds=24 * 3600)

        except Exception:
            log.exception("stats_minute_writer_loop failed; continuing")
            await asyncio.sleep(5)

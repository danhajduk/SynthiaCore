import asyncio
import time

from app.system.stats_store import StatsStore
from app.system.stats.service import collect_system_stats  # your function
from app.system.busy_rating import compute_busy_rating

store = StatsStore()

def _align_to_next_minute(ts: float) -> float:
    return (int(ts // 60) + 1) * 60.0

async def stats_sampler_loop():
    while True:
        now = time.time()
        next_min = _align_to_next_minute(now)
        await asyncio.sleep(max(0.0, next_min - now))

        # Collect snapshot
        snap = collect_system_stats()  # ideally return dict or model with .model_dump()
        snap_dict = snap.model_dump() if hasattr(snap, "model_dump") else dict(snap)

        # Compute busy rating using API metrics already embedded, or re-snapshot here
        api = snap_dict.get("api", {})
        busy = compute_busy_rating(snap_dict, api)

        # Store minute-aligned ts
        ts = next_min
        snap_dict["timestamp"] = ts
        snap_dict["busy_rating"] = round(busy, 2)

        store.insert_minute(ts=ts, busy=float(snap_dict["busy_rating"]), snapshot=snap_dict)
        store.prune_older_than(seconds=24 * 3600)

@app.on_event("startup")
async def _startup():
    asyncio.create_task(stats_sampler_loop())

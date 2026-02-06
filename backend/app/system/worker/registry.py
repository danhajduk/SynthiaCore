# backend/app/system/worker/registry.py
import asyncio
import time
from typing import Any, Dict, Awaitable, Callable

JobPayload = Dict[str, Any]
JobHandler = Callable[[JobPayload], Awaitable[Dict[str, Any]]]


async def handler_noop(payload: JobPayload) -> Dict[str, Any]:
    return {"ok": True, "handler": "noop"}


async def handler_sleep(payload: JobPayload) -> Dict[str, Any]:
    seconds = float(payload.get("seconds", 1))
    await asyncio.sleep(max(0.0, seconds))
    return {"ok": True, "handler": "sleep", "slept": seconds}

def _burn_cpu(seconds: float, intensity: int = 5000000) -> Dict[str, Any]:
    end = time.perf_counter() + max(0.0, seconds)
    acc = 0.0
    intensity = max(1000, int(intensity))
    while True:
        for _ in range(intensity):
            acc += 1.0000001
            acc *= 1.0000001
            acc += 3.14159
            acc *= 0.9999999
        if time.perf_counter() >= end:
            break
    return {"ok": True, "handler": "cpu", "burned_s": seconds, "intensity": intensity}


async def handler_cpu(payload: JobPayload) -> Dict[str, Any]:
    seconds = float(payload.get("seconds", 1))
    threads = int(payload.get("threads", 1))
    threads = max(1, min(threads, 16))
    intensity = int(payload.get("intensity", 50000))
    results = await asyncio.gather(
        *[asyncio.to_thread(_burn_cpu, seconds, intensity) for _ in range(threads)]
    )
    return {
        "ok": True,
        "handler": "cpu",
        "burned_s": seconds,
        "threads": threads,
        "intensity": intensity,
        "results": results,
    }


# Keep “helloworld.*” as first-class names,
# but alias plain names so curl tests work too.
HANDLERS: Dict[str, JobHandler] = {
    # canonical (addon) names
    "helloworld.noop": handler_noop,
    "helloworld.sleep": handler_sleep,
    "helloworld.cpu": handler_cpu,

    # aliases (generic names)
    "noop": handler_noop,
    "sleep": handler_sleep,
    "cpu": handler_cpu,
}

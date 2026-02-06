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

def _burn_cpu(seconds: float) -> Dict[str, Any]:
    end = time.perf_counter() + max(0.0, seconds)
    acc = 0.0
    while time.perf_counter() < end:
        acc += 1.0
        acc = acc * 1.0000001
        if acc > 1e9:
            acc = acc / 3.14159
    return {"ok": True, "handler": "cpu", "burned_s": seconds}


async def handler_cpu(payload: JobPayload) -> Dict[str, Any]:
    seconds = float(payload.get("seconds", 1))
    return await asyncio.to_thread(_burn_cpu, seconds)


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

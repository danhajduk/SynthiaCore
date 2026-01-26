# backend/app/system/worker/registry.py
import asyncio
from typing import Any, Dict, Awaitable, Callable

JobPayload = Dict[str, Any]
JobHandler = Callable[[JobPayload], Awaitable[Dict[str, Any]]]


async def handler_noop(payload: JobPayload) -> Dict[str, Any]:
    return {"ok": True, "handler": "noop"}


async def handler_sleep(payload: JobPayload) -> Dict[str, Any]:
    seconds = float(payload.get("seconds", 1))
    await asyncio.sleep(max(0.0, seconds))
    return {"ok": True, "handler": "sleep", "slept": seconds}


# Keep “helloworld.*” as first-class names,
# but alias plain names so curl tests work too.
HANDLERS: Dict[str, JobHandler] = {
    # canonical (addon) names
    "helloworld.noop": handler_noop,
    "helloworld.sleep": handler_sleep,

    # aliases (generic names)
    "noop": handler_noop,
    "sleep": handler_sleep,
}

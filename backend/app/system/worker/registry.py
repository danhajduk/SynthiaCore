import asyncio
from typing import Any, Dict, Awaitable, Callable

JobPayload = Dict[str, Any]
JobHandler = Callable[[JobPayload], Awaitable[Dict[str, Any]]]

async def handler_helloworld_noop(payload: JobPayload) -> Dict[str, Any]:
    return {"ok": True, "addon": "helloworld", "handler": "noop"}

async def handler_helloworld_sleep(payload: JobPayload) -> Dict[str, Any]:
    seconds = float(payload.get("seconds", 1))
    await asyncio.sleep(max(0.0, seconds))
    return {"ok": True, "addon": "helloworld", "handler": "sleep", "slept": seconds}

HANDLERS: Dict[str, JobHandler] = {
    "helloworld.noop": handler_helloworld_noop,
    "helloworld.sleep": handler_helloworld_sleep,
}

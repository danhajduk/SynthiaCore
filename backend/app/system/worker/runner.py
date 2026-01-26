# backend/app/system/worker/runner.py
from __future__ import annotations

import argparse
import asyncio
import contextlib
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from .registry import HANDLERS


@dataclass(frozen=True)
class WorkerConfig:
    base_url: str = "http://localhost:9001"
    worker_id: str = "worker-1"
    heartbeat_interval_s: float = 15.0   # must be < lease_ttl_s
    jitter_s: float = 0.25               # desync multiple workers
    max_units: Optional[int] = None      # worker-side cap
    timeout_s: float = 10.0


class WorkerRunner:
    def __init__(self, cfg: WorkerConfig) -> None:
        self.cfg = cfg
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(cfg.timeout_s))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, json: Dict[str, Any]) -> Dict[str, Any]:
        url = self.cfg.base_url.rstrip("/") + path
        r = await self._client.post(url, json=json)
        r.raise_for_status()
        return r.json()

    async def request_lease(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"worker_id": self.cfg.worker_id}
        if self.cfg.max_units is not None:
            payload["max_units"] = int(self.cfg.max_units)
        return await self._post("/api/system/scheduler/leases/request", payload)

    async def heartbeat(self, lease_id: str) -> Dict[str, Any]:
        return await self._post(
            f"/api/system/scheduler/leases/{lease_id}/heartbeat",
            {"worker_id": self.cfg.worker_id},
        )

    async def complete(
        self,
        lease_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"worker_id": self.cfg.worker_id, "status": status}
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = error
        return await self._post(f"/api/system/scheduler/leases/{lease_id}/complete", payload)

    async def _heartbeat_loop(self, lease_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(self.cfg.heartbeat_interval_s + random.uniform(0, self.cfg.jitter_s))
                await self.heartbeat(lease_id)
        except asyncio.CancelledError:
            return
        except Exception:
            # If heartbeats fail (server restart / network), lease will expire server-side.
            return

    async def run_once(self) -> None:
        res = await self.request_lease()
        print(f"[{self.cfg.worker_id}] lease response: {res}")

        if res.get("denied") is True:
            retry_ms = int(res.get("retry_after_ms", 1500))
            await asyncio.sleep((retry_ms / 1000.0) + random.uniform(0, self.cfg.jitter_s))
            return

        lease = res["lease"]
        job = res["job"]

        lease_id = lease["lease_id"]
        job_type = job.get("type", "helloworld.noop")
        payload = job.get("payload", {}) or {}

        hb_task = asyncio.create_task(self._heartbeat_loop(lease_id))

        t0 = time.time()
        try:
            handler = HANDLERS.get(job_type)
            if handler is None:
                raise RuntimeError(f"No handler registered for job type '{job_type}'")

            result = await handler(payload)
            dt = time.time() - t0

            await self.complete(
                lease_id,
                "completed",
                result={"job_type": job_type, "result": result, "duration_s": dt},
            )
            print(f"[{self.cfg.worker_id}] completed {job_type} in {dt:.3f}s")
        except Exception as e:
            await self.complete(lease_id, "failed", error=str(e))
            print(f"[{self.cfg.worker_id}] FAILED {job_type}: {e}")
        finally:
            hb_task.cancel()
            with contextlib.suppress(Exception):
                await hb_task

    async def run_forever(self) -> None:
        while True:
            await self.run_once()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Synthia worker runner (scheduler client)")
    p.add_argument("--base-url", default="http://localhost:9001")
    p.add_argument("--worker-id", default="worker-1")
    p.add_argument("--heartbeat-interval", type=float, default=15.0)
    p.add_argument("--max-units", type=int, default=None)
    p.add_argument("--timeout", type=float, default=10.0)
    return p.parse_args()


async def _amain() -> None:
    args = parse_args()
    cfg = WorkerConfig(
        base_url=args.base_url,
        worker_id=args.worker_id,
        heartbeat_interval_s=args.heartbeat_interval,
        max_units=args.max_units,
        timeout_s=args.timeout,
    )
    runner = WorkerRunner(cfg)
    try:
        await runner.run_forever()
    finally:
        await runner.aclose()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

@dataclass(frozen=True)
class ApiEvent:
    t: float          # time.time()
    path: str
    client: str
    ms: float
    status: int

def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    values.sort()
    k = int(round(0.95 * (len(values) - 1)))
    return values[k]

class ApiMetricsCollector:
    """
    Rolling in-memory window of request events.
    Cheap, good enough, and perfectly fine for a single-node SynthiaCore.
    """
    def __init__(self, max_events: int = 50_000):
        self._events: Deque[ApiEvent] = deque(maxlen=max_events)
        self._inflight: int = 0

    def _prune(self, now: float, window_s: int) -> None:
        cutoff = now - window_s
        while self._events and self._events[0].t < cutoff:
            self._events.popleft()

    def begin(self) -> None:
        self._inflight += 1

    def end(self) -> None:
        self._inflight = max(0, self._inflight - 1)

    def add(self, ev: ApiEvent) -> None:
        self._events.append(ev)

    def snapshot(self, window_s: int = 60, top_n: int = 10) -> Dict:
        now = time.time()
        self._prune(now, window_s)

        evs = list(self._events)
        n = len(evs)
        rps = (n / window_s) if window_s > 0 else 0.0

        ms_list = [e.ms for e in evs]
        avg_ms = (sum(ms_list) / len(ms_list)) if ms_list else 0.0
        p95_ms = _p95(ms_list)

        top_paths = Counter(e.path for e in evs).most_common(top_n)
        top_clients = Counter(e.client for e in evs).most_common(top_n)

        # Basic error rate (4xx/5xx)
        err = sum(1 for e in evs if e.status >= 400)
        err_rate = (err / n) if n else 0.0

        return {
            "window_s": window_s,
            "rps": round(rps, 2),
            "inflight": self._inflight,
            "latency_ms_avg": round(avg_ms, 2),
            "latency_ms_p95": round(p95_ms, 2),
            "error_rate": round(err_rate, 3),
            "top_paths": top_paths,
            "top_clients": top_clients,
        }

def _get_client_ip(request: Request, trust_proxy_headers: bool = False) -> str:
    # If you're behind nginx, set trust_proxy_headers=True and ensure only nginx can reach app.
    if trust_proxy_headers:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    client = request.client.host if request.client else "unknown"
    return client

class ApiMetricsMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        collector: ApiMetricsCollector,
        exclude_prefixes: Iterable[str] = ("/api/system/stats", "/docs", "/openapi.json"),
        trust_proxy_headers: bool = False,
    ):
        super().__init__(app)
        self.collector = collector
        self.exclude_prefixes = tuple(exclude_prefixes)
        self.trust_proxy_headers = trust_proxy_headers

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(self.exclude_prefixes):
            return await call_next(request)

        self.collector.begin()
        t0 = time.perf_counter()
        status = 500
        try:
            resp = await call_next(request)
            status = resp.status_code
            return resp
        finally:
            ms = (time.perf_counter() - t0) * 1000.0
            client = _get_client_ip(request, trust_proxy_headers=self.trust_proxy_headers)
            self.collector.add(ApiEvent(
                t=time.time(),
                path=path,
                client=client,
                ms=ms,
                status=status,
            ))
            self.collector.end()

# backend/app/system/stats/service.py
from __future__ import annotations

import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import psutil

from app.addons.discovery import repo_root
from app.addons.registry import AddonRegistry
from app.system.api_metrics import ApiMetricsCollector
from app.system.busy_rating import compute_busy_rating
from .models import (
    AddonStatsSnapshot,
    QuietAssessment,
    QuietState,
    SystemStatsSnapshot,
    SystemStats,
    LoadAvg,
    CpuStats,
    MemStats,
    SwapStats,
    DiskUsage,
    NetStats,
    NetIfaceCounters,
    NetIfaceRates,
)



def _get_uptime_s() -> float:
    # psutil boot_time is reliable on Linux
    return max(0.0, time.time() - psutil.boot_time())


def collect_system_stats(api_metrics: Optional[ApiMetricsCollector] = None) -> SystemStats:
    hostname = socket.gethostname()

    # Load averages (Linux/Unix); on platforms without it, fall back gracefully
    try:
        l1, l5, l15 = os.getloadavg()
    except (AttributeError, OSError):
        l1 = l5 = l15 = 0.0

    # CPU sampling: consistent window, avoids "0% first call" artifacts
    cpu_per = [round(v, 2) for v in psutil.cpu_percent(interval=1.0, percpu=True)]
    cpu_total = round(sum(cpu_per) / len(cpu_per), 2) if cpu_per else 0.0

    cpu = CpuStats(
        percent_total=cpu_total,
        percent_per_cpu=cpu_per,
        cores_logical=psutil.cpu_count(logical=True) or len(cpu_per) or 0,
        cores_physical=psutil.cpu_count(logical=False),
    )

    # Memory
    vm = psutil.virtual_memory()
    mem = MemStats(
        total=vm.total,
        available=vm.available,
        used=vm.used,
        free=getattr(vm, "free", 0),
        percent=vm.percent,
    )

    # Swap
    sm = psutil.swap_memory()
    swap = SwapStats(
        total=sm.total,
        used=sm.used,
        free=sm.free,
        percent=sm.percent,
    )

    # Disks
    disks: Dict[str, DiskUsage] = {}
    for p in psutil.disk_partitions(all=False):
        # Skip pseudo/readonly mounts
        if p.fstype in ("", "squashfs") or p.mountpoint.startswith(("/snap", "/var/lib/docker")):
            continue
        try:
            du = psutil.disk_usage(p.mountpoint)
            disks[p.mountpoint] = DiskUsage(
                total=du.total,
                used=du.used,
                free=du.free,
                percent=du.percent,
            )
        except PermissionError:
            continue

    # Network
    net = collect_net_stats()

    # API metrics (optional)
    api: dict = api_metrics.snapshot(window_s=60, top_n=10) if api_metrics else {}

    # Busy rating (0..10)
    busy_rating = compute_busy_rating(
        {
            "cpu": {"percent_total": cpu_total, "cores_logical": cpu.cores_logical},
            "load": {"load1": round(l1, 3), "load5": round(l5, 3), "load15": round(l15, 3)},
            "mem": {"percent": mem.percent},
            "swap": {"percent": swap.percent},
        },
        api,
    )

    return SystemStats(
        timestamp=round(time.time(), 3),
        hostname=hostname,
        uptime_s=_get_uptime_s(),
        load=LoadAvg(
            load1=round(l1, 3),
            load5=round(l5, 3),
            load15=round(l15, 3),
        ),
        cpu=cpu,
        mem=mem,
        swap=swap,
        disks=disks,
        net=net,
        api=api,
        busy_rating=round(busy_rating, 2),
    )


def collect_process_stats() -> Dict[str, Any]:
    proc = psutil.Process()
    rss = None
    cpu_pct = None
    fds = None
    threads = None
    try:
        rss = proc.memory_info().rss
    except Exception:
        pass
    try:
        cpu_pct = proc.cpu_percent(interval=None)
    except Exception:
        pass
    try:
        fds = proc.num_fds()  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        threads = proc.num_threads()
    except Exception:
        pass
    return {
        "rss_bytes": rss,
        "cpu_percent": cpu_pct,
        "open_fds": fds,
        "threads": threads,
    }


def _runtime_dir_size_bytes(path: Path, max_files: int = 5000) -> Optional[int]:
    if not path.exists():
        return 0
    total = 0
    seen = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                seen += 1
                if seen > max_files:
                    return total
                fp = os.path.join(root, name)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    continue
    except Exception:
        return None
    return total


def collect_addon_stats(registry: Optional[AddonRegistry]) -> Dict[str, AddonStatsSnapshot]:
    if registry is None:
        return {}
    addon_ids = set(registry.addons.keys()) | set(registry.errors.keys())
    out: Dict[str, AddonStatsSnapshot] = {}
    runtime_root = repo_root() / "data" / "addons"
    for addon_id in sorted(addon_ids):
        if addon_id in registry.errors:
            lifecycle = "error"
        elif not registry.is_enabled(addon_id):
            lifecycle = "disabled"
        else:
            lifecycle = "loaded"

        runtime_dir = runtime_root / addon_id / "runtime"
        runtime_bytes = _runtime_dir_size_bytes(runtime_dir)

        out[addon_id] = AddonStatsSnapshot(
            lifecycle_state=lifecycle,
            runtime_dir_bytes=runtime_bytes,
        )
    return out


def compute_quiet_assessment(busy_rating: float) -> QuietAssessment:
    # Simple mapping until a full quiet model exists.
    busy = max(0.0, min(10.0, float(busy_rating)))
    quiet_score = int(round(100 - (busy * 10)))
    if busy <= 2:
        state = QuietState.QUIET
    elif busy <= 5:
        state = QuietState.NORMAL
    elif busy <= 7:
        state = QuietState.BUSY
    else:
        state = QuietState.PANIC

    reasons = [f"busy_rating={busy:.2f}"]
    return QuietAssessment(
        quiet_score=quiet_score,
        state=state,
        reasons=reasons,
        inputs={"busy_rating": busy},
    )


def collect_system_snapshot(
    api_metrics: Optional[ApiMetricsCollector] = None,
    api_snapshot: Optional[Dict[str, Any]] = None,
    registry: Optional[AddonRegistry] = None,
) -> SystemStatsSnapshot:
    sys_snap = collect_system_stats(api_metrics=None)
    host = sys_snap.model_dump(exclude={"api", "busy_rating", "timestamp"})
    if api_snapshot is not None:
        api = api_snapshot
    else:
        api = api_metrics.snapshot(window_s=60, top_n=10) if api_metrics else {}
    process = collect_process_stats()
    addons = collect_addon_stats(registry)
    quiet = compute_quiet_assessment(sys_snap.busy_rating)

    return SystemStatsSnapshot(
        collected_at=datetime.now(timezone.utc),
        host=host,
        process=process,
        api=api,
        addons=addons,
        quiet=quiet,
        errors={},
    )


# ---- simple in-process baseline cache ----
# store last timestamp + per-interface counters (psutil returns namedtuple-like objects)
_last_net: Optional[Tuple[float, Dict[str, object]]] = None


def _net_to_model(c) -> NetIfaceCounters:
    # c is psutil.net_io_counters(...) result (a namedtuple-ish object)
    return NetIfaceCounters(
        bytes_sent=int(c.bytes_sent),
        bytes_recv=int(c.bytes_recv),
        packets_sent=int(c.packets_sent),
        packets_recv=int(c.packets_recv),
        errin=int(c.errin),
        errout=int(c.errout),
        dropin=int(c.dropin),
        dropout=int(c.dropout),
    )


def _rates_bytes(prev_sent: int, prev_recv: int, curr_sent: int, curr_recv: int, dt: float) -> NetIfaceRates:
    tx = max(0.0, (curr_sent - prev_sent) / dt)
    rx = max(0.0, (curr_recv - prev_recv) / dt)
    return NetIfaceRates(tx_Bps=round(tx, 2), rx_Bps=round(rx, 2))


def _sum_bytes(per: Dict[str, object]) -> Tuple[int, int]:
    sent = 0
    recv = 0
    for c in per.values():
        sent += int(getattr(c, "bytes_sent", 0))
        recv += int(getattr(c, "bytes_recv", 0))
    return sent, recv


def collect_net_stats() -> NetStats:
    global _last_net

    now = time.time()
    per = psutil.net_io_counters(pernic=True)
    total = psutil.net_io_counters(pernic=False)

    per_iface = {name: _net_to_model(c) for name, c in per.items()}
    total_model = _net_to_model(total)

    total_rate: Optional[NetIfaceRates] = None
    per_iface_rate: Optional[Dict[str, NetIfaceRates]] = None

    if _last_net is not None:
        last_t, last_per = _last_net
        dt = now - last_t

        if dt >= 0.25:
            # total rate from summed bytes
            prev_sent, prev_recv = _sum_bytes(last_per)
            curr_sent, curr_recv = _sum_bytes(per)
            total_rate = _rates_bytes(prev_sent, prev_recv, curr_sent, curr_recv, dt)

            # per-interface rate
            per_iface_rate = {}
            for name, curr in per.items():
                prev = last_per.get(name)
                if prev is None:
                    continue
                per_iface_rate[name] = _rates_bytes(
                    int(getattr(prev, "bytes_sent", 0)),
                    int(getattr(prev, "bytes_recv", 0)),
                    int(getattr(curr, "bytes_sent", 0)),
                    int(getattr(curr, "bytes_recv", 0)),
                    dt,
                )

    _last_net = (now, per)

    return NetStats(
        total=total_model,
        per_iface=per_iface,
        total_rate=total_rate,
        per_iface_rate=per_iface_rate,
    )

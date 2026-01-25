# backend/app/system/stats/service.py
from __future__ import annotations

import os
import socket
import time
from typing import Dict, Optional, Tuple

import psutil

from .models import (
    SystemStats, LoadAvg, CpuStats, MemStats, SwapStats, DiskUsage,
    NetStats, NetIfaceCounters, NetIfaceRates,
)
from app.system.api_metrics import ApiMetricsCollector, ApiMetricsSnapshot
from app.system.busy_rating import compute_busy_rating

timestamp: float  # epoch seconds
# ---- simple in-process baseline cache ----
_last_net: Optional[Tuple[float, Dict[str, psutil._common.snetio]]] = None
now = time()

api = api_metrics.snapshot(window_s=60, top_n=10)  # use the global collector instance
rating = compute_busy_rating(system_snapshot, api) # we’ll define next


def _get_uptime_s() -> float:
    # psutil boot_time is reliable on Linux
    return max(0.0, time.time() - psutil.boot_time())


def collect_system_stats(api_metrics: Optional[ApiMetricsCollector] = None) -> SystemStats:
    hostname = socket.gethostname()

    try:
        l1, l5, l15 = os.getloadavg()
    except (AttributeError, OSError):
        l1 = l5 = l15 = 0.0

    cpu_per = [round(v, 2) for v in psutil.cpu_percent(interval=1.0, percpu=True)]
    cpu_total = round(sum(cpu_per) / len(cpu_per), 2) if cpu_per else 0.0

    cpu = CpuStats(
        percent_total=cpu_total,
        percent_per_cpu=cpu_per,
        cores_logical=psutil.cpu_count(logical=True) or len(cpu_per) or 0,
        cores_physical=psutil.cpu_count(logical=False),
    )

    vm = psutil.virtual_memory()
    mem = MemStats(total=vm.total, available=vm.available, used=vm.used, free=getattr(vm, "free", 0), percent=vm.percent)

    sm = psutil.swap_memory()
    swap = SwapStats(total=sm.total, used=sm.used, free=sm.free, percent=sm.percent)

    disks: Dict[str, DiskUsage] = {}
    for p in psutil.disk_partitions(all=False):
        if p.fstype in ("", "squashfs") or p.mountpoint.startswith(("/snap", "/var/lib/docker")):
            continue
        try:
            du = psutil.disk_usage(p.mountpoint)
            disks[p.mountpoint] = DiskUsage(total=du.total, used=du.used, free=du.free, percent=du.percent)
        except PermissionError:
            continue

    net = collect_net_stats()

    api: Optional[ApiMetricsSnapshot] = api_metrics.snapshot(window_s=60, top_n=10) if api_metrics else None

    # compute rating from the snapshot (best effort if api is None)
    # NOTE: compute_busy_rating expects dicts in your sampler; keep consistent
    snapshot_dict = {
        "cpu": {"percent_total": cpu_total, "cores_logical": cpu.cores_logical},
        "load": {"load1": round(l1, 3), "load5": round(l5, 3), "load15": round(l15, 3)},
        "mem": {"percent": mem.percent},
        "swap": {"percent": swap.percent},
    }
    api_dict = api if isinstance(api, dict) else (api.model_dump() if api else {})
    busy_rating = compute_busy_rating(snapshot_dict, api_dict)

    return SystemStats(
        timestamp=round(time.time(), 3),
        hostname=hostname,
        uptime_s=_get_uptime_s(),
        load=LoadAvg(load1=round(l1, 3), load5=round(l5, 3), load15=round(l15, 3)),
        cpu=cpu,
        mem=mem,
        swap=swap,
        disks=disks,
        net=net,
        api=api_dict if api else None,
        busy_rating=round(busy_rating, 2),
    )


def _net_to_model(c: psutil._common.snetio) -> NetIfaceCounters:
    return NetIfaceCounters(
        bytes_sent=c.bytes_sent,
        bytes_recv=c.bytes_recv,
        packets_sent=c.packets_sent,
        packets_recv=c.packets_recv,
        errin=c.errin,
        errout=c.errout,
        dropin=c.dropin,
        dropout=c.dropout,
    )

def _rates(prev: psutil._common.snetio, curr: psutil._common.snetio, dt: float) -> NetIfaceRates:
    # bytes per second
    tx = max(0.0, (curr.bytes_sent - prev.bytes_sent) / dt)
    rx = max(0.0, (curr.bytes_recv - prev.bytes_recv) / dt)
    return NetIfaceRates(tx_Bps=round(tx, 2), rx_Bps=round(rx, 2))

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

        # Avoid divide-by-zero / tiny windows
        if dt >= 0.25:
            # total rate (recompute from totals using last "sum" if present)
            # easiest: sum pernic into a pseudo-total
            def sum_counters(d: Dict[str, psutil._common.snetio]) -> psutil._common.snetio:
                # Create a snetio-like tuple by summing fields
                # snetio: bytes_sent, bytes_recv, packets_sent, packets_recv, errin, errout, dropin, dropout
                bs = br = ps = pr = ei = eo = di = do = 0
                for c in d.values():
                    bs += c.bytes_sent; br += c.bytes_recv
                    ps += c.packets_sent; pr += c.packets_recv
                    ei += c.errin; eo += c.errout
                    di += c.dropin; do += c.dropout
                return psutil._common.snetio(bs, br, ps, pr, ei, eo, di, do)

            prev_total = sum_counters(last_per)
            curr_total = sum_counters(per)
            total_rate = _rates(prev_total, curr_total, dt)

            # per-interface rate
            per_iface_rate = {}
            for name, curr in per.items():
                prev = last_per.get(name)
                if prev is None:
                    continue
                per_iface_rate[name] = _rates(prev, curr, dt)

    # update baseline after computing
    _last_net = (now, per)

    return NetStats(
        total=total_model,
        per_iface=per_iface,
        total_rate=total_rate,
        per_iface_rate=per_iface_rate,
    )

# backend/app/system/stats/service.py
from __future__ import annotations
import os
import socket
import time
from typing import Dict

import psutil

from .models import SystemStats, LoadAvg, CpuStats, MemStats, SwapStats, DiskUsage


def _get_uptime_s() -> float:
    # psutil boot_time is reliable on Linux
    return max(0.0, time.time() - psutil.boot_time())


def collect_system_stats() -> SystemStats:
    hostname = socket.gethostname()

    # Load averages (Linux/Unix); on platforms without it, fall back gracefully
    try:
        l1, l5, l15 = os.getloadavg()
    except (AttributeError, OSError):
        l1 = l5 = l15 = 0.0

    # CPU %
    # NOTE: first call can be 0.0 unless interval is used;
    # we can accept that for "current snapshot" or do a tiny interval like 0.1
    cpu_total = psutil.cpu_percent(interval=0.1)
    cpu_per = psutil.cpu_percent(interval=None, percpu=True)

    cpu = CpuStats(
        percent_total=cpu_total,
        percent_per_cpu=cpu_per,
        cores_logical=psutil.cpu_count(logical=True) or len(cpu_per) or 0,
        cores_physical=psutil.cpu_count(logical=False),
    )

    vm = psutil.virtual_memory()
    mem = MemStats(
        total=vm.total,
        available=vm.available,
        used=vm.used,
        free=getattr(vm, "free", 0),
        percent=vm.percent,
    )

    sm = psutil.swap_memory()
    swap = SwapStats(
        total=sm.total,
        used=sm.used,
        free=sm.free,
        percent=sm.percent,
    )

    disks: Dict[str, DiskUsage] = {}
    for p in psutil.disk_partitions(all=False):
        # Skip pseudo/readonly mounts
        if p.fstype in ("", "squashfs") or p.mountpoint.startswith(("/snap", "/var/lib/docker")):
            continue
        try:
            du = psutil.disk_usage(p.mountpoint)
            disks[p.mountpoint] = DiskUsage(
                total=du.total, used=du.used, free=du.free, percent=du.percent
            )
        except PermissionError:
            continue

    return SystemStats(
        hostname=hostname,
        uptime_s=_get_uptime_s(),
        load=LoadAvg(load1=l1, load5=l5, load15=l15),
        cpu=cpu,
        mem=mem,
        swap=swap,
        disks=disks,
    )

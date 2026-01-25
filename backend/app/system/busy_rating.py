from __future__ import annotations

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def _norm(x: float, lo: float, hi: float) -> float:
    # normalize to 0..1
    if hi <= lo:
        return 0.0
    return _clamp((x - lo) / (hi - lo), 0.0, 1.0)

def compute_busy_rating(system_stats: dict, api: dict) -> float:
    """
    Returns 0..10 where:
      0-2 = idle
      3-5 = normal active
      6-7 = getting busy
      8-10 = do not schedule heavy work
    Tune thresholds once you have a day of data.
    """
    # API signals
    rps = float(api.get("rps", 0.0))
    inflight = float(api.get("inflight", 0.0))
    p95 = float(api.get("latency_ms_p95", 0.0))
    err = float(api.get("error_rate", 0.0))

    # System signals
    cpu = float(system_stats.get("cpu", {}).get("percent_total", 0.0))
    load1 = float(system_stats.get("load", {}).get("load1", 0.0))
    cores = float(system_stats.get("cpu", {}).get("cores_logical", 1) or 1)

    # Normalize (tweak as needed)
    n_p95 = _norm(p95, 50, 800)          # 50ms good; 800ms bad
    n_inflight = _norm(inflight, 1, 20)  # 1 ok; 20 means backlog
    n_rps = _norm(rps, 0.5, 25)          # depends on your polling behavior
    n_err = _norm(err, 0.01, 0.20)       # 1%..20%
    n_cpu = _norm(cpu, 10, 90)
    n_load = _norm(load1 / cores, 0.2, 1.2)  # per-core load ratio

    # Weighted blend (latency + inflight dominate)
    score01 = (
        0.30 * n_p95 +
        0.25 * n_inflight +
        0.15 * n_rps +
        0.10 * n_err +
        0.10 * n_cpu +
        0.10 * n_load
    )

    return _clamp(score01 * 10.0, 0.0, 10.0)

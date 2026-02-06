# Capacity Model

This document describes how scheduler capacity is calculated and enforced.

## Concepts
- **Total capacity units**: The maximum unit budget (default 100).
- **Reserve units**: Always held back for core system headroom.
- **Busy rating**: A 0–10 score from system and API metrics.
- **Usable capacity**: The portion of total capacity allowed at the current busy rating.
- **Leased capacity**: Units currently held by active leases.
- **Available capacity**: `usable - leased` (floored at 0).

## Busy Rating to Capacity
Capacity scales down as busy rating increases. The scheduler uses a conservative curve:

| Busy Rating | Usable % |
| --- | --- |
| 0 | 100% |
| 1 | 100% |
| 2 | 100% |
| 3 | 80% |
| 4 | 65% |
| 5 | 50% |
| 6 | 35% |
| 7 | 25% |
| 8 | 15% |
| 9 | 10% |
| 10 | 0% |

The usable units are computed as:

```
usable = floor(total_capacity_units * percent) - reserve_units
usable = max(0, usable)
```

## Enforcement
- A lease request is denied if `available <= 0`.
- A job is denied if its requested units exceed available capacity.
- If `max_units` is provided by the worker, the job’s requested units are clamped to that max.

## Fail-Closed Behavior
If system or API metrics are missing/stale, the busy rating defaults to a high value and capacity is reduced. This prevents new heavy work from running when visibility is lost.

## Snapshot Fields
Capacity appears in the scheduler snapshot as:
- `total_capacity_units`
- `usable_capacity_units`
- `leased_capacity_units`
- `available_capacity_units`

## Notes
- Capacity is recomputed on demand during lease requests and snapshots.
- This model is conservative by design to avoid system overload.

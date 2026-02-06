# Docs TODO Game Plan

1. [x] Define core models for stats and quiet assessment.
2. [x] Implement collectors: host, process, addon, and API middleware stats.
3. [x] Build in-memory stats snapshot and `/api/system-stats/current`.
4. [x] Add SQLite storage for samples and `/api/system-stats/history`.
5. [x] Implement quiet streak tracking and `/api/system-stats/health`.
6. [ ] Add scheduler missing pieces: capacity headroom calc, concurrency backstops.
7. [ ] Add scheduler endpoints: `report` and `revoke`.
8. [ ] Persist scheduler lease events and expose per-addon decision summary.
9. [ ] Implement queueing: `JobIntent`, queue store, dispatcher, state transitions.
10. [ ] Add queue persistence (SQLite) if required for crash safety.
11. [ ] Add config model and safe defaults for intervals/thresholds/limits.
12. [ ] Add tests: unit for quiet score/policy/token bucket/expiry; integration for snapshot and endpoints.
13. [ ] Tackle future enhancements (custom addon stats, downsampling, Prometheus, UI widgets).

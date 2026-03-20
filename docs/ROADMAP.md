# Hexe Roadmap

Last Updated: 2026-03-07 14:51 US/Pacific

Date established: 2026-02-28  
Status: Active source of truth

## Purpose
This document is the canonical roadmap for planned engineering work.  
Legacy TODO documents were archived under `docs/archive/`.

## Current Priorities
1. Store cleanup and hardening (post Phase 1)
- modularize store lifecycle internals
- add request-level API tests
- improve operator visibility and audit surfaces
- tighten retention/cleanup behavior

2. Addon store Phase 2+
- publisher workflow and release pipeline
- entitlement and billing integration hooks
- policy and org governance controls
- telemetry and operational analytics

3. Platform consistency
- align architecture docs with current control-plane behavior
- keep one active task tracker and archive stale plans
- preserve fail-closed behavior on security-sensitive paths

## Tracking Rules
1. New execution tasks should be added to the active local task list (`docs/New_tasks.txt`) when in active development.
2. Completed work should be appended to `completed_task.txt`.
3. Avoid creating additional parallel TODO sources in `docs/`.

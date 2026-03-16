# Supervisor Lifecycle Control

Status: Implemented

This document defines the current Supervisor-managed lifecycle semantics for host-local managed nodes.

## Source Of Truth

- `backend/app/supervisor/service.py`
- `backend/app/supervisor/models.py`
- `backend/synthia_supervisor/models.py`
- `backend/synthia_supervisor/main.py`

## Lifecycle States

Current lifecycle states:

- `unknown`
- `starting`
- `running`
- `stopping`
- `stopped`
- `restarting`
- `error`

## Action Semantics

### Start

- sets desired state to `running`
- writes lifecycle state `starting`
- executes compose up for the managed node
- writes lifecycle state `running` on success
- writes lifecycle state `error` on failure

### Stop

- sets desired state to `stopped`
- writes lifecycle state `stopping`
- executes compose down for the managed node
- writes lifecycle state `stopped` on success
- writes lifecycle state `error` on failure

### Restart

- sets desired state to `running`
- writes lifecycle state `restarting`
- executes compose down then compose up
- writes lifecycle state `running` on success
- writes lifecycle state `error` on failure

## Runtime Metadata

Supervisor now owns these runtime metadata fields in `runtime.json`:

- `lifecycle_state`
- `last_action`
- `last_action_at`

These fields are surfaced through Supervisor-managed node summaries and lifecycle action responses.

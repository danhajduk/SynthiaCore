# Core Scheduler Docs

This folder is the canonical home for Core scheduler documentation.

## Included Docs

- [job-model.md](./job-model.md)

## Status

Status: Partially implemented

This documentation was re-homed from `docs/scheduler/` during the Core -> Supervisor -> Nodes migration.

## Boundary

- Scheduler remains a Core subsystem.
- Its canonical role is workload admission, queue management, and orchestration.
- Execution should be described separately from scheduler ownership.
- Admission now reads Supervisor runtime readiness when that service is available.

## See Also

- [../../workers/README.md](../../workers/README.md)
- [../api/api-reference.md](../api/api-reference.md)
- [../../overview.md](../../overview.md)

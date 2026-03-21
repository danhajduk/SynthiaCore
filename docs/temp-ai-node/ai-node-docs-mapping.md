# AI Node Docs Mapping

Last Updated: 2026-03-11

## Ownership Decision

Status: Planned

- Canonical source location: `/home/dan/Projects/HexeAiNode/docs`
- Sync direction: node-first
- Golden repo role (`/home/dan/Projects/Hexe/docs`): index, mapping, and subsystem cross-reference only

## Mapping Table

| AI Node Canonical File | Golden Docs Counterpart | Owner | Sync Direction | Notes |
| --- | --- | --- | --- | --- |
| `/home/dan/Projects/HexeAiNode/docs/ai-node-architecture.md` | `docs/architecture.md`, `docs/mqtt/mqtt-platform.md` | AI Node repo | Node -> Golden references | Golden docs link to this architecture source; no duplicate copy in golden repo. |
| `/home/dan/Projects/HexeAiNode/docs/node-capability-declaration.md` | `docs/core/api/api-reference.md`, `docs/architecture.md` | AI Node repo | Node -> Golden references | Capability declaration remains planned; golden API docs should reference when implemented endpoints exist. |
| `/home/dan/Projects/HexeAiNode/docs/phase1-overview.md` | `docs/overview.md`, `docs/operators-guide.md` | AI Node repo | Node -> Golden references | Phase 1 onboarding flow is maintained in node docs and cross-linked from golden index. |

## Update Workflow

1. Update canonical AI Node docs in `/home/dan/Projects/HexeAiNode/docs`.
2. Update this mapping file if ownership/sync rules change.
3. Update golden index links when file names/paths change.

## See Also

- [Document Index](../index.md)
- [Overview](../overview.md)
- [Architecture](../architecture.md)
- [MQTT Platform](../mqtt/mqtt-platform.md)
- [API Reference](../core/api/api-reference.md)

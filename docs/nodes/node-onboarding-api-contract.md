# Node Onboarding API Contract

Status: Implemented (baseline), Partial (multi-node-type rollout in progress)
Last updated: 2026-03-11

## Purpose

Defines the canonical global node onboarding session API contract used by Core.

## Start Session

- `POST /api/system/nodes/onboarding/sessions`
- Request fields:
  - `node_name`
  - `node_type`
  - `node_software_version`
  - `protocol_version`
  - `node_nonce`
  - `hostname` (optional)
- Response includes canonical and compatibility fields:
  - `node_name`, `node_type`, `node_software_version`
  - `requested_node_name`, `requested_node_type`, `requested_node_software_version` (compatibility aliases)
  - `approval_url`, `session_id`, `expires_at`, `finalize`

## Approval And Decision

- `GET /api/system/nodes/onboarding/sessions/{session_id}?state=...` (admin auth)
- `POST /api/system/nodes/onboarding/sessions/{session_id}/approve?state=...` (admin auth)
- `POST /api/system/nodes/onboarding/sessions/{session_id}/reject?state=...` (admin auth)

Decision response includes session data and registration data when approved.

## Finalization

- `GET /api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=...`
- Outcome set:
  - `pending`
  - `approved` (returns one-time trust activation payload)
  - `rejected`
  - `expired`
  - `consumed`
  - `invalid`

## Registration Query

- `GET /api/system/nodes/registrations` (admin auth)
- `GET /api/system/nodes/registrations/{node_id}` (admin auth)

Supports optional list filters:
- `node_type`
- `trust_status`

## Node Type Support

Supported node types are configured by:
- `SYNTHIA_NODE_ONBOARDING_SUPPORTED_TYPES`

Default:
- `ai-node`

## Compatibility Layer

Legacy AI-node alias routes are available under:
- `/api/system/ai-nodes/onboarding/sessions*`

Alias responses include:
- `Deprecation: true`
- `Sunset: 2026-09-30`
- warning header with migration direction

## See Also

- [Node Onboarding Phase 1 Contract](./node-onboarding-phase1-contract.md)
- [Node Onboarding And Registration Architecture](./node-onboarding-registration-architecture.md)
- [Node Trust Activation Payload Contract](./node-trust-activation-payload-contract.md)
- [Node Onboarding Migration Guide](./node-onboarding-migration-guide.md)

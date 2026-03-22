# Node Onboarding API Contract

Status: Implemented (baseline), Partial (multi-node-type rollout in progress)
Last updated: 2026-03-22

## Purpose

Defines the canonical global node onboarding session API contract used by Hexe Core.

Terminology note:

- `onboarding session` is the canonical pre-trust flow term
- `registration record` is the canonical persisted identity term
- `trust activation` is the canonical finalize payload term
- `AI-node` remains compatibility/profile terminology only

## Start Session

- `POST /api/system/nodes/onboarding/sessions`
- Request fields:
  - `node_name`
  - `node_type`
  - `node_software_version`
  - `protocol_version`
  - `node_nonce`
  - `hostname` (optional)
  - `ui_endpoint` (optional absolute `http://` or `https://` URL for the node-hosted operator UI)
- Response includes canonical and compatibility fields:
  - `node_name`, `node_type`, `node_software_version`
  - `requested_node_name`, `requested_node_type`, `requested_node_software_version` (compatibility aliases)
  - `requested_hostname`, `requested_ui_endpoint`
  - `approval_url`, `session_id`, `expires_at`, `finalize`

UI endpoint rules:
- Core accepts `ui_endpoint` only as an absolute `http(s)` URL.
- Core persists the value as `requested_ui_endpoint` on the onboarding session and registration record.
- Core node UI route `/nodes/:nodeId/UI` prefers `requested_ui_endpoint` and falls back to `requested_hostname` when no explicit endpoint was provided.
- Core serves that route through the node UI proxy so root-relative node assets are requested back through `/nodes/{node_id}/ui/...`.
- `hostname` remains supported as a lightweight identity/location hint and fallback UI target source.

## Approval And Decision

- `GET /api/system/nodes/onboarding/sessions/{session_id}?state=...` (admin auth)
- `POST /api/system/nodes/onboarding/sessions/{session_id}/approve?state=...` (admin auth)
- `POST /api/system/nodes/onboarding/sessions/{session_id}/reject?state=...` (admin auth)

Decision response includes session data and registration data when approved.

Approval URL contract:
- generated form is `<core_base>/onboarding/nodes/approve?sid=<session_id>&state=<state_token>`
- `state` is required for approval page and decision validation
- decision actions also require authenticated admin context

## Finalization

- `GET /api/system/nodes/onboarding/sessions/{session_id}/finalize?node_nonce=...`
- Outcome set:
  - `pending`
  - `approved` (returns one-time trust activation payload)
  - `rejected`
  - `expired`
  - `consumed`
  - `invalid`

Deterministic behavior rules:
- start-session does not issue trust credentials
- duplicate active sessions for the same binding return `duplicate_active_session`
- invalid session ids or nonce mismatches return `invalid`
- approved finalization returns trust activation payload from Core trust issuance
- first successful approved finalization marks the session consumed
- replayed approved finalization attempts return `consumed`

## Registration Query

- `GET /api/system/nodes/registrations` (admin auth)
- `GET /api/system/nodes/registrations/{node_id}` (admin auth)
- `GET /api/system/nodes/trust-status/{node_id}` (node trust token or admin auth)

Registration payloads include canonical Core-side UI metadata:
- `ui_enabled`
- `ui_base_url`
- `ui_mode`
- `ui_health_endpoint`

Registry UI metadata rules:
- `ui_base_url` is normalized to an absolute `http://` or `https://` URL when present.
- for legacy records, Core derives UI metadata from `requested_ui_endpoint` first and then `requested_hostname`
- `ui_mode` defaults to `spa` for nodes
- missing UI metadata remains safe and explicit through `ui_enabled = false`

Current node API proxy assumption:
- `GET|POST|PUT|PATCH|DELETE /api/nodes/{node_id}/{path...}` proxies to the same node origin as `ui_base_url`
- Core strips the `/api/nodes/{node_id}` prefix before forwarding
- until nodes publish a dedicated API base field, Core derives the upstream API base from the `ui_base_url` origin

Supports optional list filters:
- `node_type`
- `trust_status`

Trust-status behavior:

- provides an explicit Core-side trust decision for active, revoked, or removed nodes
- remains readable with the node's last issued trust token after revocation/removal
- exists so nodes can distinguish deliberate Core trust loss from generic transport or auth failures

## Node Type Support

Supported node types are configured by:
- `SYNTHIA_NODE_ONBOARDING_SUPPORTED_TYPES`

Default:
- `ai-node`
- `email-node`

## Compatibility Layer

Legacy AI-node alias routes are available under:
- `/api/system/ai-nodes/onboarding/sessions*`

Alias responses include:
- `Deprecation: true`
- `Sunset: 2026-09-30`
- warning header with migration direction

## Headless Compatibility

Status: Implemented (baseline)

- nodes do not need embedded browser capability for onboarding
- nodes only need to present the approval URL to an operator
- operator login and approval happen in Core independently from the node runtime

## See Also

- [Node Onboarding And Trust Terminology](./onboarding-trust-terminology.md)
- [Node Onboarding Phase 1 Contract](./node-onboarding-phase1-contract.md)
- [Node Onboarding And Registration Architecture](./node-onboarding-registration-architecture.md)
- [Node Trust Activation Payload Contract](./node-trust-activation-payload-contract.md)
- [Node Trust Status Contract](./node-trust-status-contract.md)
- [Node Onboarding Migration Guide](./node-onboarding-migration-guide.md)
- [Node Onboarding Start Request JSON Schema](../json_schema/node_onboarding_start_request.schema.json)

# MQTT Embedded Addon/Platform Contract

Last Updated: 2026-03-09 06:36 US/Pacific

## Contract Decision

MQTT should operate as a platform-managed embedded addon with limited uninstall/disable behavior.

Rationale:
- MQTT underpins platform event-plane and policy distribution flows.
- Treating it as fully removable creates control-plane reliability and boot-order risk for Core.

## Core-Side Contract

Embedded package conventions:
- backend entry: `addons/mqtt/backend/addon.py`
- frontend entry: `addons/mqtt/frontend/index.ts`

Platform-role constraints:
- MQTT embedded component is discoverable like other embedded addons for UI/inventory consistency.
- Uninstall is blocked for platform-role MQTT.
- Disable behavior is restricted or policy-gated (not equivalent to ordinary optional addons).

Authority and runtime split:
- Core authority state is canonical.
- Embedded MQTT runtime consumes Core-approved state.
- Generated broker/runtime artifacts are data plane outputs, not source of truth.

## API and Discovery Alignment

Aligned with existing addon docs:
- Embedded addon file layout and exports remain standard.
- API-first control plane remains standard for deterministic operations.
- MQTT event topics remain async visibility/transport.

Migration compatibility:
- Existing `/api/system/mqtt/registrations/*` routes may remain temporarily while semantics are shifted from remote provisioning calls to Core-owned embedded authority actions.

## Not Developed

- Final enforcement implementation for protected uninstall/disable behavior in registry/store admin paths.
- Final embedded MQTT addon package implementation under `addons/mqtt/*`.

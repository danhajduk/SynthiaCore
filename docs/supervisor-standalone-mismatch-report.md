# Task 114: Mismatch Report (`docs/supervisor.md` vs `docs/standalone-addon.md`)

Comparison date: 2026-03-07

Scope:
- `docs/supervisor.md`
- `docs/standalone-addon.md`
- Code spot-checks for validation:
  - `backend/synthia_supervisor/docker_compose.py`
  - `backend/app/store/router.py`

## Summary

Found 4 material mismatches (normative statements that are stricter in `standalone-addon.md` than what supervisor behavior guarantees).

## Mismatch 1: "Unsupported" network/privileged claims are too absolute

Standalone doc says runtime does not support:
- host network mode
- privileged containers

Location:
- `docs/standalone-addon.md` section "13. Unsupported Features"

Supervisor/code reality:
- Generated compose template sets `privileged: false` and does not generate host network mode.
- But supervisor only writes compose when missing; existing compose files are preserved.
- Therefore a custom pre-existing compose file can still include host networking or privileged settings.

Code evidence:
- `backend/synthia_supervisor/docker_compose.py`: `if compose_file.exists(): ... return`
- `backend/synthia_supervisor/docker_compose.py`: generated template includes `privileged: false`
- `backend/app/store/router.py`: install-time guardrails reject host/privileged overrides for Core-authored desired runtime, but this is not a universal supervisor enforcement layer.

Resolution suggestion:
- Reword standalone doc as "not supported by Core-generated runtime intent/template" instead of absolute runtime impossibility.

## Mismatch 2: Direct filesystem mounts claim is not enforceable by current supervisor

Standalone doc says runtime does not support direct filesystem mounts.

Location:
- `docs/standalone-addon.md` section "13. Unsupported Features"

Supervisor/code reality:
- Supervisor does not enforce a no-volume policy if compose file already exists.
- Existing compose file is reused unchanged.

Code evidence:
- `backend/synthia_supervisor/docker_compose.py`: compose file generation is skipped when file exists.

Resolution suggestion:
- Reword to indicate mounts are not present in generated template, but not globally prevented by supervisor.

## Mismatch 3: Runtime exec commands claim is not represented by supervisor controls

Standalone doc says runtime does not support runtime container exec commands.

Location:
- `docs/standalone-addon.md` section "13. Unsupported Features"

Supervisor/code reality:
- Supervisor simply does not expose an exec feature/API.
- This is an API-surface absence, not an enforceable runtime prohibition.

Resolution suggestion:
- Reword as "no supervisor-managed exec API is implemented".

## Mismatch 4: Required env vars are overstated at supervisor layer

Standalone doc lists `SYNTHIA_ADDON_ID`, `SYNTHIA_SERVICE_TOKEN`, `CORE_URL` as required injected variables.

Locations:
- `docs/standalone-addon.md` sections "4. Environment Variables" and "7. Addon Identity"

Supervisor/code reality:
- Supervisor writes env file from desired config env.
- Supervisor only injects `SYNTHIA_SERVICE_TOKEN` if process env contains it.
- Core install path typically supplies these defaults, but supervisor alone does not guarantee all three in every reconcile source.

Code evidence:
- `backend/synthia_supervisor/docker_compose.py`: env file from `desired.config.env`; token added with `setdefault` only when env var is present.
- `backend/app/store/router.py`: Core install path defines defaults for these keys.

Resolution suggestion:
- Reword as "required by Core-authored standalone install flow" or "expected by default Core intent", not unconditional supervisor guarantee.

## Non-mismatched / aligned points

Aligned between both docs:
- Verification/checksum enforcement disabled during current development phase.
- Supervisor is polling-based and not a sandbox.
- Health probing is not developed.
- Resource limits are not developed.

## Recommended next action

Update `docs/standalone-addon.md` to soften absolute prohibitions into code-verified scope language (template/default behavior vs globally enforced behavior).

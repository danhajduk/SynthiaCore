# SSAP Standalone Service Operator Runbook

This runbook covers lifecycle operations for SSAP standalone services managed by Core + Supervisor.

`/api/store/install` now accepts standalone-oriented request contract fields (`install_mode`, `channel`, `desired_state`, `pinned_version`, runtime/config overrides) that are used by the direct standalone install path.
When `channel` is provided, release selection stays within that channel (`stable`, `beta`, or `nightly`) instead of cross-channel fallback.
Artifact staging for standalone installs is atomic (`*.tmp` then replace) and reuses an existing `addon.tgz` when its SHA-256 already matches the resolved release checksum.
When install request uses `install_mode=standalone_service` and the release profile matches, Core writes `desired.json` directly and returns standalone path metadata instead of rejecting the install.
Core validates desired payloads before writing and returns `ssap_desired_invalid` if request overrides would produce invalid SSAP state.
Guardrails are enforced at install-intent time: host networking and privileged overrides are rejected, and `SYNTHIA_SERVICE_TOKEN` is always included in desired config env for supervisor/env-file injection.
Install responses now surface supervisor indicators from `runtime.json` (`runtime_state`, `active_version`, `last_action`) and return `supervisor_hint` when runtime state is still unknown.
Troubleshooting response fields include absolute `desired_path`, `runtime_path`, `staged_artifact_path`, `service_dir`, and minimal `next_steps` guidance.

## Install API Contract

`POST /api/store/install` standalone fields:

- `source_id` (required for catalog installs)
- `addon_id` (required for catalog installs)
- `version` (optional exact release)
- `channel` (`stable|beta|nightly`, default `stable`)
- `install_mode` (`embedded_addon|standalone_service`)
- `desired_state` (`running|stopped`, default `running`)
- `pinned_version` (optional; defaults to resolved release version for standalone mode)
- `runtime_overrides` (optional `project_name`, `network`, `ports`, `bind_localhost`)
- `config_env_overrides` (optional env map merged into `config.env`)

Frontend contract:

- Addon Store maps catalog `package_profile` to install request `install_mode`.
- `standalone_service` profile cards send `install_mode=standalone_service`.
- `embedded_addon` (or unknown profile fallback) cards send `install_mode=embedded_addon`.
- If backend returns `remediation_path=standalone_service_install`, retry from Addon Store should succeed without manual payload edits.

Standalone success response fields:

- `mode`, `requested_install_mode`, `version`
- `desired_path`, `runtime_path`, `staged_artifact_path`, `service_dir`
- `runtime_state`, `active_version`, `last_action`, `supervisor_hint`
- `registry_state`, `security_guardrails`, `next_steps`

## Paths and Ownership

- Desired state file:
  - `SynthiaAddons/services/<addon_id>/desired.json`
  - Owned by Core/operator intent.
- Runtime state file:
  - `SynthiaAddons/services/<addon_id>/runtime.json`
  - Owned by Supervisor reconcile loop.
- Versioned artifacts:
  - `SynthiaAddons/services/<addon_id>/versions/<version>/addon.tgz`
  - Staged by Core from catalog installs.
- Active pointer:
  - `SynthiaAddons/services/<addon_id>/current` symlink
  - Switched by Supervisor only after successful `docker compose up`.
- Deployment recommendation:
  - Prefer `SYNTHIA_ADDONS_DIR` outside the Core repo (for example `~/.local/share/synthia/SynthiaAddons`) so updater `git reset --hard` operations remain isolated from SSAP runtime state.

## Install

1. Trigger catalog install from Core (`/api/store/install`).
2. Core verifies artifact, then stages it into:
   - `services/<addon_id>/versions/<version>/addon.tgz`
3. Core writes/updates desired state (`desired.json`) via SSAP fields.
4. Supervisor loop sees desired running state, verifies staged artifact again, then reconciles runtime.

## Start

1. Set `desired_state` to `running` in `desired.json`.
2. Supervisor sequence:
   1. Verify checksum/signature.
   2. Extract artifact.
   3. Generate compose/env files with security defaults.
   4. Run `docker compose up`.
   5. Atomically switch `current` symlink to new version.
3. Supervisor writes `runtime.json` with `state=running`.

## Stop

1. Set `desired_state` to `stopped` in `desired.json`.
2. Supervisor runs `docker compose down` for current version.
3. Supervisor writes `runtime.json` with `state=stopped`.

## Upgrade

1. Stage new version artifact under `versions/<new_version>/addon.tgz`.
2. Update `desired.json` `pinned_version` to new version.
3. Supervisor performs normal running reconcile and switches `current` only after successful start.
4. `runtime.json` tracks `active_version` and previous-version metadata.

## Rollback

On activation failure, Supervisor does not switch `current` and writes failure metadata in `runtime.json`:

- `state: "error"`
- `previous_version`
- `rollback_available`
- `last_error`

Rollback operation:

1. Point desired state back to prior working version (`pinned_version=<previous_version>`).
2. Keep `desired_state=running`.
3. Let Supervisor reconcile and reactivate previous version.

## Runtime Security Defaults

Generated compose/env defaults enforce:

- `privileged: false`
- `security_opt: [no-new-privileges:true]`
- Dedicated network (`synthia_net` by default)
- Localhost-bound published ports (`127.0.0.1:<host>:<container>/<proto>`)
- Env-file injection for service token (`SYNTHIA_SERVICE_TOKEN`)

## Troubleshooting

- SHA mismatch:
  - Check staged artifact hash and catalog release `sha256`.
  - Re-stage artifact from trusted catalog source.
- Signature failure:
  - Verify publisher key id and detached signature value in catalog metadata.
  - Confirm `publishers.json` path and active key status.
- Compose startup failure:
  - Inspect Supervisor `runtime.json:last_error`.
  - Inspect `docker compose` logs for service build/start errors.
- Missing MQTT announce/health:
  - Verify service runtime is `running`.
  - Verify addon publishes retained announce/health topics and broker connectivity.
- Supervisor process logs:
  - `journalctl --user -u synthia-supervisor -n 200 --no-pager`

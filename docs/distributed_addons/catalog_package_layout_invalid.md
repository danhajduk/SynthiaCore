# Why `catalog_package_layout_invalid` Happens

This error means Core tried to install a catalog artifact as an embedded addon package, but the package layout does not match embedded-addon requirements.

## Error Breakdown

Input error:

- `error=catalog_package_layout_invalid`: The package layout did not match install policy.
- `reason=missing_backend_entrypoint`: Required embedded entrypoint was not found.
- `expected_package_profile=embedded_addon`: Core install path accepts embedded addon packages.
- `expected_backend_entrypoint=backend/addon.py`: Embedded package must include this file.
- `layout_hint=service_layout_app_main`: Installer detected `app/main.py` pattern.
- `detected_package_profile=standalone_service`: Artifact looks like a standalone service package.

## Root Cause

The artifact at `artifact_url` contains a standalone-service structure (`app/main.py`) instead of embedded-addon structure (`backend/addon.py`).

Because install was requested through catalog embedded install flow, Core validated it against embedded-addon structure and rejected it.

## What This Is Not

- Not a signature failure.
- Not a checksum failure.
- Not a source refresh failure.

It is a package-structure mismatch between requested install mode and artifact layout.

## Fix Checklist

Choose one profile and keep package layout + catalog metadata consistent.

### Option A: Keep Embedded Addon Install (`embedded_addon`)

Use this if you want to install from Core store as an embedded addon.

1. In the addon artifact, provide:
   - `manifest.json` at addon root.
   - `backend/addon.py` entrypoint.
2. Set catalog release `package_profile` to `embedded_addon`.
3. Build and publish new artifact (`.zip`/`.tgz`) with embedded layout.
4. Update catalog release fields to match new artifact:
   - `artifact_url`
   - signature (`release_sig`)
   - checksum (`sha256`/`checksum`)
5. Refresh source in Core, then retry install.

### Option B: Keep Standalone Service (`standalone_service`)

Use this if the addon is a separate service process with `app/main.py`.

1. Keep service layout in addon artifact (`app/main.py` etc.).
2. Set catalog release `package_profile` to `standalone_service`.
3. Do not use embedded install path for that artifact.
4. Deploy service externally (container/systemd/host process).
5. Register service endpoint in Core:
   - `POST /api/admin/addons/registry`
   - include `addon_id` and reachable `base_url`.
6. Validate service health/announce flow and proxy behavior.

### Validation After Fix

1. Confirm `/api/store/install` no longer returns `catalog_package_layout_invalid`.
2. Confirm `/api/store/status/{addon_id}` has no new layout error in `last_install_error`.
3. If standalone path was chosen, confirm addon appears in registry and responds through proxy/API.

## Recurrence Check (Example: `v0.1.2`)

If the same error appears for a newer tag (for example `v0.1.2`), it means the newly published artifact still has standalone-service layout while Core install flow expects embedded-addon layout.

Use this quick check on the addon artifact before catalog update:

```bash
curl -L -o /tmp/addon.tgz https://github.com/danhajduk/Synthia-MQTT/releases/download/v0.1.2/addon.tgz
tar -tzf /tmp/addon.tgz | head -n 40
```

Interpretation:
- If you see `app/main.py` and no `backend/addon.py`, it is `standalone_service`.
- If you see `backend/addon.py` (with valid `manifest.json`), it can be used as `embedded_addon`.

Only publish catalog metadata that matches the packaged layout (`package_profile` + artifact structure).

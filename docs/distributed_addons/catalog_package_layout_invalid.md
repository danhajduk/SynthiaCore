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

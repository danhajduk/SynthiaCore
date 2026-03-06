# Catalog Release Publish Checklist

Use this checklist before merging/publishing a catalog release entry.

## 1) Package Profile/Layout Validation (Required)

Run:

```bash
scripts/validate-catalog-package-profile.sh <package_profile> <artifact_path>
```

Examples:

```bash
scripts/validate-catalog-package-profile.sh embedded_addon /tmp/addon.tgz
scripts/validate-catalog-package-profile.sh standalone_service /tmp/addon.tgz
```

Gate:
- `embedded_addon` must contain `backend/addon.py`.
- `standalone_service` must contain `app/main.py` and must not contain `backend/addon.py`.
- If the command exits non-zero, do not publish that release metadata.

## 2) Catalog Metadata Alignment (Required)

Verify catalog release fields match published artifact bytes:
- `package_profile` matches layout validation result.
- `artifact_url` points to the exact artifact validated.
- `sha256`/`checksum` correspond to that artifact.
- detached signature metadata corresponds to that artifact.

Validate release version fields before publish:

```bash
scripts/validate-catalog-release-versions.py /path/to/catalog/v1/index.json
```

Gate:
- every release `version` must be semver (`1.2.3`) or semver+suffix (`1.2.3d`).
- if validator exits non-zero, do not publish.

## 3) Rollback Safety (Required)

If a profile/layout mismatch is discovered after publication:
- pin install guidance to last known-good release,
- keep mismatch release out of promoted channel until fixed,
- publish corrected artifact+metadata pair as a new release.

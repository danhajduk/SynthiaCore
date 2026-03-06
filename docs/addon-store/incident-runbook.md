# Addon Store Incident Runbook

This runbook covers store install incidents returning:
- `catalog_artifact_unavailable`

Use it during operator triage and recovery for `POST /api/store/install`.

## 1. Immediate Triage Snapshot

1. Capture install response payload (`detail` object).
2. Capture addon store status payload:
   - `GET /api/store/status/{addon_id}`
   - record `installed_from_source_id`, `installed_resolved_base_url`, and `last_install_error`.
3. Capture source cache metadata:
   - `runtime/store/cache/<source_id>/metadata.json`
4. Capture recent store logs:
   - `logs/addons.log`
   - `logs/core.log`
   - `logs/system.log`
   - `logs/api.log`

## 2. Refresh Catalog Cache First

1. Trigger one manual refresh:

```bash
curl -sS -X POST \
  -H "X-Admin-Token: ${SYNTHIA_ADMIN_TOKEN}" \
  "http://127.0.0.1:8000/api/store/sources/<source_id>/refresh"
```

2. Confirm refresh result is `ok` and note:
   - `catalog_status.source_id`
   - `catalog_status.resolved_base_url`
   - `catalog_status.last_success_at`

If refresh is not `ok`, resolve catalog signature/connectivity issues before retrying install.

## 3. Incident: `catalog_artifact_unavailable`

Meaning: catalog release metadata resolved to an artifact URL that still returns `404` after backend refresh + retry.

1. Read failing artifact from install response or `/api/store/status/{addon_id}` `last_install_error.artifact_url`.
2. Verify URL manually:

```bash
curl -I "<artifact_url>"
```

3. Verify release entry in cached catalog index:
   - file: `runtime/store/cache/<source_id>/index.json`
   - confirm the release `artifact_url`/`artifact.url` matches an existing upstream asset.
4. Validate upstream release state (GitHub release/tag/asset exists and is public).
5. Recovery options:
   - refresh source again if upstream asset was just published,
   - install pinned previous known-good addon release,
   - if official catalog is wrong upstream, wait for catalog correction and avoid repeated retries.

## 4. Rollback Path

If production is impacted:

1. Keep currently installed known-good addon version running.
2. If a bad install already occurred, uninstall and reinstall known-good package:
   - `POST /api/store/uninstall`
   - `POST /api/store/install` (local package mode using verified artifact + manifest + key)
3. Re-enable addon only after artifact URL and release metadata are verified by operator checks.
4. Record incident notes with:
   - failing source id,
   - resolved base URL,
   - artifact URL,
   - timestamp and operator actions.

## 5. Exit Criteria

Incident is closed only when:
- source refresh is healthy,
- artifact URL is reachable,
- install returns `200`,
- `/api/store/status/{addon_id}` has `last_install_error = null`.

#!/usr/bin/env bash
set -euo pipefail

units=(
  "synthia-backend.service"
  "synthia-frontend-dev.service"
)
updater_unit="synthia-updater.service"
supervisor_unit="synthia-supervisor.service"
supervisor_api_unit="synthia-supervisor-api.service"
dashboard_unit="synthia-dashboard.service"

echo "[reload-all] Reloading user systemd units"
systemctl --user daemon-reload

if systemctl --user cat "$supervisor_unit" >/dev/null 2>&1; then
  units+=("$supervisor_unit")
else
  echo "[reload-all] Supervisor unit not installed; skipping $supervisor_unit"
fi
if systemctl --user cat "$supervisor_api_unit" >/dev/null 2>&1; then
  units+=("$supervisor_api_unit")
else
  echo "[reload-all] Supervisor API unit not installed; skipping $supervisor_api_unit"
fi

if systemctl --user cat "$dashboard_unit" >/dev/null 2>&1; then
  units+=("$dashboard_unit")
else
  echo "[reload-all] Dashboard unit not installed; skipping $dashboard_unit"
fi

echo "[reload-all] Restarting: ${units[*]}"
systemctl --user restart "${units[@]}"

echo "[reload-all] Starting updater oneshot: ${updater_unit}"
systemctl --user start "${updater_unit}"

echo "[reload-all] Status"
systemctl --user --no-pager --full status "${units[@]}" "${updater_unit}" || true

echo "[reload-all] Done"
pkill chrome

#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_DIR/.config/hexe/admin.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi

LOG_FILE="${LOG_FILE:-/tmp/hexe_update.log}"
SERVICE_UPDATE=false
PLATFORM_NAME="${PLATFORM_NAME:-Hexe AI}"

usage() {
  cat <<EOF
Usage:
  update.sh [--service_update]

Options:
  --service_update   reinstall systemd user units from templates
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service_update) SERVICE_UPDATE=true; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 1;;
  esac
done

exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== [update] $(date -Is) starting ${PLATFORM_NAME} update ==="
echo "[update] repo=$REPO_DIR"

cd "$REPO_DIR"

RAW_ADDONS_DIR="${SYNTHIA_ADDONS_DIR:-../SynthiaAddons}"
if [[ "$RAW_ADDONS_DIR" = /* ]]; then
  RESOLVED_ADDONS_DIR="$(realpath -m "$RAW_ADDONS_DIR")"
else
  RESOLVED_ADDONS_DIR="$(realpath -m "$REPO_DIR/backend/$RAW_ADDONS_DIR")"
fi
if [[ "$RESOLVED_ADDONS_DIR" == "$REPO_DIR"* ]]; then
  echo "[update] WARN: SYNTHIA_ADDONS_DIR resolves inside repo ($RESOLVED_ADDONS_DIR)."
  echo "[update] WARN: use an external path (for example ~/.local/share/hexe/HexeAddons) to keep SSAP state isolated from code updates."
fi

echo "[update] git fetch/reset"
git fetch --all --prune
git reset --hard origin/main

echo "[update] backend deps"
cd "$REPO_DIR/backend"
source .venv/bin/activate
pip install -r requirements.txt
deactivate

echo "[update] frontend deps"
cd "$REPO_DIR/frontend"
npm install

echo "[update] sync addon frontends"
cd "$REPO_DIR"
if [[ -x "$REPO_DIR/scripts/sync-addons-frontend.sh" ]]; then
  "$REPO_DIR/scripts/sync-addons-frontend.sh"
fi
echo "[update] configure frontend API target"
"$REPO_DIR/scripts/configure-frontend-api.sh"

if [[ "$SERVICE_UPDATE" == "true" ]]; then
  echo "[update] reinstalling systemd user units"
  UNIT_SRC_DIR="$REPO_DIR/systemd/user"
  UNIT_DST_DIR="$HOME/.config/systemd/user"
  SUPERVISOR_UNIT="hexe-supervisor.service"
  SUPERVISOR_API_UNIT="hexe-supervisor-api.service"
  DASHBOARD_UNIT="hexe-dashboard.service"
  mkdir -p "$UNIT_DST_DIR"

  install_unit() {
    local template="$1"
    local out="$2"
    if [[ ! -f "$template" ]]; then
      echo "[update] ERROR: missing unit template: $template"
      exit 1
    fi
    sed "s|@INSTALL_DIR@|$REPO_DIR|g" "$template" > "$out"
  }

  install_unit "$UNIT_SRC_DIR/hexe-backend.service.in" "$UNIT_DST_DIR/hexe-backend.service"
  install_unit "$UNIT_SRC_DIR/hexe-frontend-dev.service.in" "$UNIT_DST_DIR/hexe-frontend-dev.service"
  install_unit "$UNIT_SRC_DIR/hexe-updater.service.in" "$UNIT_DST_DIR/hexe-updater.service"
  if [[ -f "$UNIT_SRC_DIR/${DASHBOARD_UNIT}.in" ]]; then
    install_unit "$UNIT_SRC_DIR/${DASHBOARD_UNIT}.in" "$UNIT_DST_DIR/${DASHBOARD_UNIT}"
  else
    echo "[update] WARN: missing optional unit template: $UNIT_SRC_DIR/${DASHBOARD_UNIT}.in"
  fi
  if [[ -f "$UNIT_SRC_DIR/${SUPERVISOR_UNIT}.in" ]]; then
    install_unit "$UNIT_SRC_DIR/${SUPERVISOR_UNIT}.in" "$UNIT_DST_DIR/${SUPERVISOR_UNIT}"
  else
    echo "[update] WARN: missing optional unit template: $UNIT_SRC_DIR/${SUPERVISOR_UNIT}.in"
  fi
  if [[ -f "$UNIT_SRC_DIR/${SUPERVISOR_API_UNIT}.in" ]]; then
    install_unit "$UNIT_SRC_DIR/${SUPERVISOR_API_UNIT}.in" "$UNIT_DST_DIR/${SUPERVISOR_API_UNIT}"
  else
    echo "[update] WARN: missing optional unit template: $UNIT_SRC_DIR/${SUPERVISOR_API_UNIT}.in"
  fi

  if command -v sudo >/dev/null 2>&1; then
    TMPFILES_SRC="$REPO_DIR/systemd/tmpfiles.d/hexe.conf"
    TMPFILES_DST="/etc/tmpfiles.d/hexe.conf"
    if [[ -f "$TMPFILES_SRC" ]]; then
      echo "[update] installing /run/hexe tmpfiles rule"
      sudo install -m 0644 "$TMPFILES_SRC" "$TMPFILES_DST" || true
      sudo systemd-tmpfiles --create "$TMPFILES_DST" || true
    else
      echo "[update] WARN: missing tmpfiles template: $TMPFILES_SRC"
    fi
  else
    echo "[update] WARN: sudo unavailable; /run/hexe must be created manually"
  fi

  systemctl --user daemon-reload
  systemctl --user restart hexe-backend.service
  systemctl --user restart hexe-frontend-dev.service
  if [[ -f "$UNIT_DST_DIR/${DASHBOARD_UNIT}" ]]; then
    systemctl --user restart "$DASHBOARD_UNIT"
  fi
  if [[ -f "$UNIT_DST_DIR/${SUPERVISOR_UNIT}" ]]; then
    systemctl --user restart "$SUPERVISOR_UNIT"
  fi
  if [[ -f "$UNIT_DST_DIR/${SUPERVISOR_API_UNIT}" ]]; then
    systemctl --user restart "$SUPERVISOR_API_UNIT"
  fi
fi

echo "[update] restart services"
systemctl --user restart hexe-backend.service
systemctl --user restart hexe-frontend-dev.service
if systemctl --user cat hexe-dashboard.service >/dev/null 2>&1; then
  systemctl --user restart hexe-dashboard.service
fi
if systemctl --user cat hexe-supervisor.service >/dev/null 2>&1; then
  systemctl --user restart hexe-supervisor.service
fi
if systemctl --user cat hexe-supervisor-api.service >/dev/null 2>&1; then
  systemctl --user restart hexe-supervisor-api.service
fi


echo "=== [update] $(date -Is) finished ${PLATFORM_NAME} update ==="

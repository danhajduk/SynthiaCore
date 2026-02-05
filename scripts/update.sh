#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="${LOG_FILE:-/tmp/synthia_update.log}"
SERVICE_UPDATE=false

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

echo "=== [update] $(date -Is) starting ==="
echo "[update] repo=$REPO_DIR"

cd "$REPO_DIR"

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

  install_unit "$UNIT_SRC_DIR/synthia-backend.service.in" "$UNIT_DST_DIR/synthia-backend.service"
  install_unit "$UNIT_SRC_DIR/synthia-frontend-dev.service.in" "$UNIT_DST_DIR/synthia-frontend-dev.service"
  install_unit "$UNIT_SRC_DIR/synthia-updater.service.in" "$UNIT_DST_DIR/synthia-updater.service"

  systemctl --user daemon-reload
  systemctl --user restart synthia-backend.service
  systemctl --user restart synthia-frontend-dev.service
fi

echo "[update] restart services"
systemctl --user restart synthia-backend.service
systemctl --user restart synthia-frontend-dev.service


echo "=== [update] $(date -Is) finished ==="

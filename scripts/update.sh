#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="${LOG_FILE:-/tmp/synthia_update.log}"

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

echo "[update] restart services"
systemctl --user restart synthia-backend.service
systemctl --user restart synthia-frontend-dev.service

journalctl --user -u synthia-backend.service -f
systemctl --user status synthia-backend.service

echo "=== [update] $(date -Is) finished ==="

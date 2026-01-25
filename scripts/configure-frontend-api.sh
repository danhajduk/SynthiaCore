#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$REPO_DIR/frontend"

BACKEND_HOST="${SYNTHIA_BACKEND_HOST:-HomeAssistant.local}"
BACKEND_PORT="${SYNTHIA_BACKEND_PORT:-9001}"

IP="$(getent ahostsv4 "$BACKEND_HOST" | awk '{print $1; exit}')"

if [[ -z "$IP" ]]; then
  echo "[configure] ERROR: Could not resolve $BACKEND_HOST"
  exit 1
fi

API_TARGET="http://${IP}:${BACKEND_PORT}"

cat > "$FRONTEND_DIR/.env.development" <<EOF
# Auto-generated (do not edit)
VITE_API_TARGET=${API_TARGET}
EOF

echo "[configure] VITE_API_TARGET=${API_TARGET}"

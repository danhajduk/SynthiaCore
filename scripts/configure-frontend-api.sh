#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$REPO_DIR/frontend"

BACKEND_HOST="${SYNTHIA_BACKEND_HOST:-}"
BACKEND_PORT="${SYNTHIA_BACKEND_PORT:-9001}"

resolve_host() {
  local host="$1"
  if [[ -z "$host" ]]; then
    echo ""
    return
  fi
  if [[ "$host" =~ ^[0-9]+(\.[0-9]+){3}$ ]]; then
    echo "$host"
    return
  fi
  getent ahostsv4 "$host" | awk '{print $1; exit}'
}

if [[ -z "$BACKEND_HOST" ]]; then
  # Prefer the first non-loopback IP on this host
  BACKEND_HOST="$(hostname -I | awk '{print $1}')"
  if [[ -z "$BACKEND_HOST" ]]; then
    BACKEND_HOST="127.0.0.1"
  fi
fi

IP="$(resolve_host "$BACKEND_HOST")"

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

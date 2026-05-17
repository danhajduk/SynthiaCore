#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-${0:-}}")" && pwd)"
LOCAL_INSTALLER="$SCRIPT_DIR/supervisor_install.sh"
RAW_BASE="${HEXE_RAW_BASE_URL:-https://raw.githubusercontent.com/danhajduk/HexeCore/main/core}"

if [[ -f "$LOCAL_INSTALLER" ]]; then
  exec "$LOCAL_INSTALLER" "$@"
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "[install-supervisor] curl is required when running outside a checkout." >&2
  exit 1
fi

curl -fsSL "$RAW_BASE/scripts/supervisor_install.sh" | bash -s -- "$@"

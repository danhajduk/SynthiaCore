#!/usr/bin/env bash
set -euo pipefail

# Convenience dev launcher (optional)
# Sources scripts/synthia.env for shared configuration.

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_DIR/scripts/synthia.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi
# Runs backend (9001) and frontend (5173) in separate terminals if available.

echo "Backend: uvicorn app.main:app --reload --port 9001 (in ./backend)"
echo "Frontend: npm run dev -- --port 5173 (in ./frontend)"
echo "Note: npm run dev auto-syncs addon frontends via predev."

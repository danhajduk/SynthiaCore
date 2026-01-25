#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADDONS_DIR="$PROJECT_ROOT/addons"
FRONTEND_ADDONS="$PROJECT_ROOT/frontend/src/addons"

mkdir -p "$FRONTEND_ADDONS"

echo "[SYNTHIA] Syncing frontend addons..."

# Clean existing synced entries (but keep .gitkeep)
find "$FRONTEND_ADDONS" -mindepth 1 -maxdepth 1 ! -name ".gitkeep" -exec rm -rf {} +

for addon in "$ADDONS_DIR"/*; do
  [ -d "$addon" ] || continue
  name="$(basename "$addon")"
  src="$addon/frontend"
  dest="$FRONTEND_ADDONS/$name"

  if [ -d "$src" ]; then
    ln -s "../../../addons/$name/frontend" "$dest"
    echo " - linked $name"
  fi
done

echo "[SYNTHIA] Done."

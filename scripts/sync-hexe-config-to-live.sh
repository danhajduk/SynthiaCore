#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$REPO_DIR/.config/hexe"
DST_DIR="$HOME/.config/hexe"

usage() {
  cat <<EOF
Usage:
  scripts/sync-hexe-config-to-live.sh [--file NAME]

Options:
  --file NAME   Sync only one file from .config/hexe (for example admin.env)
EOF
}

TARGET_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --file)
      TARGET_FILE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[sync-hexe-config] Unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ ! -d "$SRC_DIR" ]]; then
  echo "[sync-hexe-config] Missing repo config dir: $SRC_DIR" >&2
  exit 1
fi

mkdir -p "$DST_DIR"

sync_one() {
  local name="$1"
  local src="$SRC_DIR/$name"
  local dst="$DST_DIR/$name"
  if [[ ! -f "$src" ]]; then
    echo "[sync-hexe-config] Missing source file: $src" >&2
    exit 1
  fi
  cp "$src" "$dst"
  case "$name" in
    *.env) chmod 600 "$dst" ;;
    *) chmod 644 "$dst" ;;
  esac
  echo "[sync-hexe-config] synced $src -> $dst"
}

if [[ -n "$TARGET_FILE" ]]; then
  sync_one "$TARGET_FILE"
  exit 0
fi

found_any=false
for path in "$SRC_DIR"/*; do
  if [[ -f "$path" ]]; then
    found_any=true
    sync_one "$(basename "$path")"
  fi
done

if [[ "$found_any" != true ]]; then
  echo "[sync-hexe-config] No files found in $SRC_DIR" >&2
  exit 1
fi

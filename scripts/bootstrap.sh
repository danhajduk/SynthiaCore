#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/danhajduk/SynthiaCore.git"

usage() {
  cat <<EOF
Usage:
  bootstrap.sh --dir <install_dir> --install
  bootstrap.sh --dir <install_dir> --update

Examples:
  bootstrap.sh --dir "\$HOME/Projects/Synthia" --install
  bootstrap.sh --dir "\$HOME/Projects/Synthia" --update
EOF
}

INSTALL_DIR=""
MODE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2;;
    --install) MODE="install"; shift;;
    --update) MODE="update"; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 1;;
  esac
done

[[ -n "$INSTALL_DIR" ]] || { echo "Missing --dir"; usage; exit 1; }
[[ -n "$MODE" ]] || { echo "Missing --install or --update"; usage; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1"; exit 1; }; }

need_cmd git
need_cmd python
need_cmd pip
need_cmd node
need_cmd npm
need_cmd systemctl

mkdir -p "$(dirname "$INSTALL_DIR")"

if [[ "$MODE" == "install" ]]; then
  if [[ -e "$INSTALL_DIR/.git" ]]; then
    echo "[bootstrap] Repo already exists at $INSTALL_DIR"
  else
    echo "[bootstrap] Cloning $REPO_URL -> $INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
  fi
fi

cd "$INSTALL_DIR"

echo "[bootstrap] Fetching latest"
git fetch --all --prune
git reset --hard origin/main

echo "[bootstrap] Backend venv + deps"
cd "$INSTALL_DIR/backend"
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo "[bootstrap] Frontend deps"
cd "$INSTALL_DIR/frontend"
npm install

echo "[bootstrap] Sync addon frontends"
cd "$INSTALL_DIR"
./scripts/sync-addons-frontend.sh

# ---------- systemd user services ----------
echo "[bootstrap] Installing user systemd units"
mkdir -p "$HOME/.config/systemd/user"
cp -f "$INSTALL_DIR/systemd/user/"*.service "$HOME/.config/systemd/user/"

systemctl --user daemon-reload

# Optional but recommended: keep user services running without an active login session
if command -v loginctl >/dev/null 2>&1; then
  echo "[bootstrap] Enabling linger for $USER (requires sudo once, ignore if you don't want this)"
  sudo loginctl enable-linger "$USER" || true
fi

echo "[bootstrap] Enabling + starting services"
systemctl --user enable --now synthia-backend.service
systemctl --user enable --now synthia-frontend-dev.service

echo "[bootstrap] Done."
echo "Check:"
echo "  systemctl --user status synthia-backend.service"
echo "  systemctl --user status synthia-frontend-dev.service"

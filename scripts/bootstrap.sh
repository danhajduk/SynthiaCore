#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_DIR/scripts/synthia.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi

REPO_URL_DEFAULT="https://github.com/danhajduk/SynthiaCore.git"
REPO_URL="${REPO_URL:-$REPO_URL_DEFAULT}"

INSTALL_DIR=""
MODE=""

usage() {
  cat <<EOF
Usage:
  bootstrap.sh --dir <install_dir> --install
  bootstrap.sh --dir <install_dir> --update

Optional env:
  REPO_URL=...   (defaults to $REPO_URL_DEFAULT)
EOF
}

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

need_cmd() { command -v "$1" >/dev/null 2>&1; }

ensure_deps() {
  local missing=()

  need_cmd git || missing+=("git")
  need_cmd python3 || missing+=("python3")
  need_cmd node || missing+=("nodejs")
  need_cmd npm || missing+=("npm")
  need_cmd systemctl || missing+=("systemd")

  python3 -c "import venv" >/dev/null 2>&1 || missing+=("python3-venv")
  need_cmd pip3 || missing+=("python3-pip")

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "[bootstrap] Missing deps: ${missing[*]}"
    echo "[bootstrap] Installing via apt (sudo required)..."
    sudo apt update
    sudo apt install -y "${missing[@]}"
  fi
}

install_user_unit_from_template() {
  local template="$1"
  local out="$2"

  if [[ ! -f "$template" ]]; then
    echo "[bootstrap] ERROR: missing unit template: $template"
    exit 1
  fi

  # Substitute @INSTALL_DIR@ safely (sed delimiter = |)
  sed "s|@INSTALL_DIR@|$INSTALL_DIR|g" "$template" > "$out"
}

echo "[bootstrap] mode=$MODE dir=$INSTALL_DIR"
ensure_deps

mkdir -p "$(dirname "$INSTALL_DIR")"

if [[ "$MODE" == "install" ]]; then
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "[bootstrap] Repo already exists at $INSTALL_DIR"
  else
    echo "[bootstrap] Cloning $REPO_URL -> $INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
  fi
fi

cd "$INSTALL_DIR"
echo "[bootstrap] Updating code"
git fetch --all --prune
git reset --hard origin/main

echo "[bootstrap] Backend venv + deps"
cd "$INSTALL_DIR/backend"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo "[bootstrap] Frontend deps"
cd "$INSTALL_DIR/frontend"
npm install

echo "[bootstrap] Sync addon frontends"
cd "$INSTALL_DIR"
if [[ -x "$INSTALL_DIR/scripts/sync-addons-frontend.sh" ]]; then
  "$INSTALL_DIR/scripts/sync-addons-frontend.sh"
else
  echo "[bootstrap] WARN: scripts/sync-addons-frontend.sh not found/executable; skipping"
fi

echo "[bootstrap] Ensure update script exists + executable"
if [[ ! -f "$INSTALL_DIR/scripts/update.sh" ]]; then
  echo "[bootstrap] ERROR: missing scripts/update.sh (required for updater service)"
  exit 1
fi
chmod +x "$INSTALL_DIR/scripts/update.sh"

echo "[bootstrap] Admin token env"
mkdir -p "$HOME/.config/synthia"
ENVFILE="$HOME/.config/synthia/admin.env"
if [[ ! -f "$ENVFILE" ]]; then
  TOKEN="$(python3 -c 'import secrets; print("SYNTHIA_ADMIN_TOKEN="+secrets.token_urlsafe(48))')"
  echo "$TOKEN" > "$ENVFILE"
  chmod 600 "$ENVFILE"
  echo "[bootstrap] Created $ENVFILE"
else
  echo "[bootstrap] Using existing $ENVFILE"
fi

echo "[bootstrap] Installing systemd user units from repo templates"
UNIT_SRC_DIR="$INSTALL_DIR/systemd/user"
UNIT_DST_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DST_DIR"

install_user_unit_from_template \
  "$UNIT_SRC_DIR/synthia-backend.service.in" \
  "$UNIT_DST_DIR/synthia-backend.service"

install_user_unit_from_template \
  "$UNIT_SRC_DIR/synthia-frontend-dev.service.in" \
  "$UNIT_DST_DIR/synthia-frontend-dev.service"

install_user_unit_from_template \
  "$UNIT_SRC_DIR/synthia-updater.service.in" \
  "$UNIT_DST_DIR/synthia-updater.service"

systemctl --user daemon-reload

if command -v loginctl >/dev/null 2>&1; then
  echo "[bootstrap] Enabling linger for $USER (optional)"
  sudo loginctl enable-linger "$USER" || true
fi
echo "[update] configure frontend API target"
REPO_DIR="$INSTALL_DIR"
"$REPO_DIR/scripts/configure-frontend-api.sh"

echo "[bootstrap] Enabling + starting services"
set +e
systemctl --user enable --now synthia-backend.service
BACKEND_RC=$?
systemctl --user enable --now synthia-frontend-dev.service
FRONTEND_RC=$?
set -e

if [[ $BACKEND_RC -ne 0 ]]; then
  echo "[bootstrap] ERROR: backend failed"
  systemctl --user status synthia-backend.service --no-pager || true
  journalctl --user -u synthia-backend.service -n 120 --no-pager || true
  exit 1
fi

if [[ $FRONTEND_RC -ne 0 ]]; then
  echo "[bootstrap] ERROR: frontend failed"
  systemctl --user status synthia-frontend-dev.service --no-pager || true
  journalctl --user -u synthia-frontend-dev.service -n 120 --no-pager || true
  exit 1
fi

echo "[bootstrap] Done."
echo "Backend:  http://$(hostname -I | awk '{print $1}'):9001/api/health"
echo "Frontend: http://$(hostname -I | awk '{print $1}'):5173"
echo "Updater unit installed: synthia-updater.service (trigger via: systemctl --user start synthia-updater.service)"

#!/usr/bin/env bash
set -euo pipefail

REPO_URL_DEFAULT="https://github.com/danhajduk/HexeCore.git"
REPO_URL="${REPO_URL:-$REPO_URL_DEFAULT}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-}"
DEFAULT_CORE_INSTALL_DIR="$HOME/hexe/hexe/core"
DEFAULT_SUPERVISOR_INSTALL_DIR="$HOME/hexe/hexe/supervisor"
START_SERVICES=true
REFRESH_REPO=false
INSTALL_MODE="${HEXE_SUPERVISOR_INSTALL_MODE:-}"
SUPERVISOR_SOCKET="${HEXE_SUPERVISOR_SOCKET:-/run/hexe/supervisor.sock}"
CORE_URL="${HEXE_SUPERVISOR_CORE_URL:-${SYNTHIA_CORE_URL:-}}"
CORE_TOKEN="${HEXE_SUPERVISOR_CORE_TOKEN:-${SYNTHIA_ADMIN_TOKEN:-}}"
CORE_TOKEN_KIND="${HEXE_SUPERVISOR_CORE_TOKEN_KIND:-}"
ENROLLMENT_TOKEN="${HEXE_SUPERVISOR_ENROLLMENT_TOKEN:-}"
CORE_URL_ARG=false
CORE_TOKEN_ARG=false
ENROLLMENT_TOKEN_ARG=false
SUPERVISOR_ID="${HEXE_SUPERVISOR_ID:-}"
SUPERVISOR_NAME="${HEXE_SUPERVISOR_NAME:-}"
SUPERVISOR_PUBLIC_URL="${HEXE_SUPERVISOR_PUBLIC_URL:-}"
REPORT_INTERVAL_S="${HEXE_SUPERVISOR_REPORT_INTERVAL_S:-15}"

script_repo_dir() {
  local source_path="${BASH_SOURCE[0]:-${0:-}}"
  if [[ -n "$source_path" && -f "$source_path" ]]; then
    local script_dir
    script_dir="$(cd "$(dirname "$source_path")" && pwd)"
    local candidate
    candidate="$(cd "$script_dir/.." && pwd)"
    if [[ -d "$candidate/backend/synthia_supervisor" && -d "$candidate/systemd/user" ]]; then
      printf "%s\n" "$candidate"
      return 0
    fi
  fi
  return 1
}

usage() {
  cat <<EOF
Usage:
  supervisor_install.sh [--dir INSTALL_DIR] [--repo-url URL] [--branch NAME] [--refresh] [--no-start]
                        [--standalone | --join-core | --bundled-core]
                        [--core-url URL] [--enrollment-token TOKEN | --admin-token TOKEN] [--supervisor-id ID]
                        [--supervisor-name NAME] [--public-url URL]

Curl install:
  curl -fsSL https://raw.githubusercontent.com/danhajduk/HexeCore/main/core/scripts/install-supervisor.sh | bash -s -- --standalone
  curl -fsSL https://raw.githubusercontent.com/danhajduk/HexeCore/main/core/scripts/install-supervisor.sh | bash -s -- --join-core --core-url http://core-host:9001 --enrollment-token TOKEN --supervisor-id host-a
  curl -fsSL https://raw.githubusercontent.com/danhajduk/HexeCore/main/core/scripts/install-supervisor.sh | bash -s -- --bundled-core

Options:
  --dir INSTALL_DIR  Checkout to use or create. Defaults to $DEFAULT_SUPERVISOR_INSTALL_DIR for standalone/join-core and $DEFAULT_CORE_INSTALL_DIR for bundled-core.
  --repo-url URL     Git repository to clone when INSTALL_DIR does not exist. Default: $REPO_URL_DEFAULT
  --branch NAME      Branch to clone or refresh. Default: main
  --refresh          Fast-forward an existing checkout before installing.
  --no-start         Install units without starting them.
  --standalone       Install Supervisor as an independent local app. It does not report to Core.
  --join-core        Install Supervisor as a remote host joined to Core. Requires --core-url and --supervisor-id.
  --bundled-core     Install Supervisor beside a local Core checkout. This is the Core-bundled mode.
  --core-url URL     Core API base URL for remote Supervisor reporting.
  --enrollment-token TOKEN
                    One-time Core-issued Supervisor enrollment token. The installer exchanges this for a reporting token and does not persist the one-time token.
  --one-time-token TOKEN
                    Alias for --enrollment-token.
  --admin-token TOKEN
                    Core admin token used directly by the Supervisor reporter. Prefer --enrollment-token for remote hosts.
  --supervisor-id ID Stable ID for this host Supervisor.
  --supervisor-name NAME
                    Display name for this host Supervisor.
  --public-url URL   Optional Core-reachable Supervisor API URL.
  --report-interval SECONDS
                    Remote reporting interval. Default: 15.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --standalone)
      INSTALL_MODE="standalone"
      shift
      ;;
    --join-core)
      INSTALL_MODE="join-core"
      shift
      ;;
    --bundled-core)
      INSTALL_MODE="bundled-core"
      shift
      ;;
    --dir)
      INSTALL_DIR="${2:-}"
      shift 2
      ;;
    --repo-url)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --branch)
      BRANCH="${2:-}"
      shift 2
      ;;
    --refresh)
      REFRESH_REPO=true
      shift
      ;;
    --no-start)
      START_SERVICES=false
      shift
      ;;
    --core-url)
      CORE_URL="${2:-}"
      CORE_URL_ARG=true
      shift 2
      ;;
    --admin-token)
      CORE_TOKEN="${2:-}"
      CORE_TOKEN_KIND="admin"
      CORE_TOKEN_ARG=true
      shift 2
      ;;
    --enrollment-token|--one-time-token)
      ENROLLMENT_TOKEN="${2:-}"
      ENROLLMENT_TOKEN_ARG=true
      shift 2
      ;;
    --supervisor-id)
      SUPERVISOR_ID="${2:-}"
      shift 2
      ;;
    --supervisor-name)
      SUPERVISOR_NAME="${2:-}"
      shift 2
      ;;
    --public-url)
      SUPERVISOR_PUBLIC_URL="${2:-}"
      shift 2
      ;;
    --report-interval)
      REPORT_INTERVAL_S="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[supervisor-install] Unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

infer_install_mode() {
  if [[ -n "$INSTALL_MODE" ]]; then
    case "$INSTALL_MODE" in
      standalone|join-core|bundled-core)
        return 0
        ;;
      *)
        echo "[supervisor-install] Invalid install mode: $INSTALL_MODE" >&2
        usage
        exit 1
        ;;
    esac
  fi

  if [[ -n "$CORE_URL" ]]; then
    INSTALL_MODE="join-core"
  else
    INSTALL_MODE="standalone"
  fi
}

load_existing_supervisor_env() {
  local env_file="$HOME/.config/hexe/supervisor.env"
  if [[ ! -f "$env_file" ]]; then
    return 0
  fi

  # shellcheck source=/dev/null
  source "$env_file"

  if [[ -z "$INSTALL_MODE" && -n "${HEXE_SUPERVISOR_INSTALL_MODE:-}" ]]; then
    INSTALL_MODE="$HEXE_SUPERVISOR_INSTALL_MODE"
  fi
  if [[ -z "$CORE_URL" && -n "${HEXE_SUPERVISOR_CORE_URL:-}" ]]; then
    CORE_URL="$HEXE_SUPERVISOR_CORE_URL"
  fi
  if [[ -z "$SUPERVISOR_ID" && -n "${HEXE_SUPERVISOR_ID:-}" ]]; then
    SUPERVISOR_ID="$HEXE_SUPERVISOR_ID"
  fi
  if [[ -z "$SUPERVISOR_NAME" && -n "${HEXE_SUPERVISOR_NAME:-}" ]]; then
    SUPERVISOR_NAME="$HEXE_SUPERVISOR_NAME"
  fi
  if [[ -z "$SUPERVISOR_PUBLIC_URL" && -n "${HEXE_SUPERVISOR_PUBLIC_URL:-}" ]]; then
    SUPERVISOR_PUBLIC_URL="$HEXE_SUPERVISOR_PUBLIC_URL"
  fi
  if [[ -z "$CORE_TOKEN" && -z "$ENROLLMENT_TOKEN" && -n "${HEXE_SUPERVISOR_CORE_TOKEN:-}" ]]; then
    CORE_TOKEN="$HEXE_SUPERVISOR_CORE_TOKEN"
    CORE_TOKEN_KIND="${HEXE_SUPERVISOR_CORE_TOKEN_KIND:-supervisor}"
  fi
}

validate_install_mode() {
  infer_install_mode

  if [[ "$INSTALL_MODE" == "standalone" ]]; then
    if [[ "$CORE_URL_ARG" == "true" || "$CORE_TOKEN_ARG" == "true" || "$ENROLLMENT_TOKEN_ARG" == "true" ]]; then
      echo "[supervisor-install] --standalone cannot be combined with --core-url, --admin-token, or --enrollment-token." >&2
      exit 1
    fi
    CORE_URL=""
    CORE_TOKEN=""
    CORE_TOKEN_KIND=""
    ENROLLMENT_TOKEN=""
  fi

  if [[ "$INSTALL_MODE" == "join-core" ]]; then
    if [[ -z "$CORE_URL" ]]; then
      echo "[supervisor-install] --join-core requires --core-url." >&2
      exit 1
    fi
    if [[ -z "$SUPERVISOR_ID" ]]; then
      echo "[supervisor-install] --join-core requires --supervisor-id." >&2
      exit 1
    fi
    if [[ -n "$ENROLLMENT_TOKEN" && "$CORE_TOKEN_ARG" != "true" ]]; then
      CORE_TOKEN=""
      CORE_TOKEN_KIND=""
    fi
    if [[ -n "$CORE_TOKEN" && -n "$ENROLLMENT_TOKEN" ]]; then
      echo "[supervisor-install] --join-core accepts either --enrollment-token or --admin-token, not both." >&2
      exit 1
    fi
    if [[ -z "$CORE_TOKEN" && -z "$ENROLLMENT_TOKEN" ]]; then
      echo "[supervisor-install] --join-core requires --enrollment-token or --admin-token." >&2
      exit 1
    fi
    if [[ -n "$CORE_TOKEN" && -z "$CORE_TOKEN_KIND" ]]; then
      CORE_TOKEN_KIND="admin"
    fi
  fi
}

load_existing_supervisor_env
validate_install_mode

if [[ -z "$INSTALL_DIR" ]]; then
  if [[ "$INSTALL_MODE" == "bundled-core" ]]; then
    INSTALL_DIR="$DEFAULT_CORE_INSTALL_DIR"
  else
    INSTALL_DIR="$DEFAULT_SUPERVISOR_INSTALL_DIR"
  fi
fi

if [[ -z "$REPO_URL" || -z "$BRANCH" || -z "$INSTALL_DIR" ]]; then
  echo "[supervisor-install] Missing required install settings." >&2
  usage
  exit 1
fi

APP_DIR="$INSTALL_DIR"
REPO_SUBDIR=""

need_cmd() { command -v "$1" >/dev/null 2>&1; }

install_missing_deps() {
  local missing=("$@")
  if (( ${#missing[@]} == 0 )); then
    return 0
  fi

  echo "[supervisor-install] Missing deps: ${missing[*]}"
  if need_cmd sudo && need_cmd apt-get; then
    echo "[supervisor-install] Installing missing deps via apt (sudo required)..."
    sudo apt-get update
    sudo apt-get install -y "${missing[@]}"
    return 0
  fi

  echo "[supervisor-install] Install the missing dependencies and rerun this script." >&2
  exit 1
}

ensure_deps() {
  local missing=()

  need_cmd curl || missing+=("curl")
  need_cmd git || missing+=("git")
  need_cmd python3 || missing+=("python3")
  need_cmd systemctl || missing+=("systemd")
  python3 -c "import venv" >/dev/null 2>&1 || missing+=("python3-venv")

  install_missing_deps "${missing[@]}"
}

clone_or_refresh_repo() {
  if [[ ! -d "$INSTALL_DIR" ]]; then
    local clone_dir="$INSTALL_DIR"
    REPO_SUBDIR=""
    if [[ "$INSTALL_MODE" == "bundled-core" ]]; then
      REPO_SUBDIR="core"
    else
      REPO_SUBDIR="supervisor"
    fi

    echo "[supervisor-install] Cloning $REPO_URL ($BRANCH) -> $INSTALL_DIR"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    if [[ "$REPO_SUBDIR" == "." ]]; then
      git clone --branch "$BRANCH" "$REPO_URL" "$clone_dir"
      return 0
    fi

    clone_dir="$(mktemp -d "${TMPDIR:-/tmp}/hexe-supervisor-install.XXXXXX")"
    git clone --branch "$BRANCH" "$REPO_URL" "$clone_dir/repo"
    if [[ ! -d "$clone_dir/repo/$REPO_SUBDIR" ]]; then
      echo "[supervisor-install] Cloned repo is missing expected subdir: $REPO_SUBDIR" >&2
      rm -rf "$clone_dir"
      exit 1
    fi
    mkdir -p "$INSTALL_DIR"
    (cd "$clone_dir/repo/$REPO_SUBDIR" && tar -cf - .) | (cd "$INSTALL_DIR" && tar -xf -)
    rm -rf "$clone_dir"
    return 0
  fi

  if [[ ! -d "$INSTALL_DIR/.git" ]]; then
    if [[ -d "$INSTALL_DIR/core" && -d "$INSTALL_DIR/supervisor" ]]; then
      echo "[supervisor-install] ERROR: $INSTALL_DIR looks like a full HexeCore checkout nested in the Supervisor install directory." >&2
      echo "[supervisor-install] Remove it or rerun with --dir pointing at the intended parent checkout." >&2
      exit 1
    fi
    echo "[supervisor-install] Using existing non-git install dir: $INSTALL_DIR"
    return 0
  fi

  if [[ "$REFRESH_REPO" == "true" ]]; then
    echo "[supervisor-install] Refreshing checkout at $INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch origin "$BRANCH"
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
  else
    echo "[supervisor-install] Using existing checkout at $INSTALL_DIR"
  fi
}

resolve_app_dir() {
  APP_DIR="$INSTALL_DIR"
  if [[ -d "$APP_DIR/backend/synthia_supervisor" && -d "$APP_DIR/systemd/user" ]]; then
    return 0
  fi

  if [[ "$INSTALL_MODE" == "bundled-core" && -d "$INSTALL_DIR/core/backend/synthia_supervisor" ]]; then
    APP_DIR="$INSTALL_DIR/core"
    return 0
  fi

  if [[ "$INSTALL_MODE" != "bundled-core" && -d "$INSTALL_DIR/supervisor/backend/synthia_supervisor" ]]; then
    APP_DIR="$INSTALL_DIR/supervisor"
    return 0
  fi

  if [[ -d "$INSTALL_DIR/core/backend/synthia_supervisor" ]]; then
    APP_DIR="$INSTALL_DIR/core"
  fi
}

ensure_repo_layout() {
  local missing=()
  [[ -f "$APP_DIR/backend/requirements.txt" ]] || missing+=("backend/requirements.txt")
  [[ -d "$APP_DIR/backend/synthia_supervisor" ]] || missing+=("backend/synthia_supervisor")
  [[ -f "$APP_DIR/systemd/user/hexe-supervisor.service.in" ]] || missing+=("systemd/user/hexe-supervisor.service.in")
  [[ -f "$APP_DIR/systemd/user/hexe-supervisor-api.service.in" ]] || missing+=("systemd/user/hexe-supervisor-api.service.in")

  if (( ${#missing[@]} > 0 )); then
    echo "[supervisor-install] Supervisor app dir is missing required files: $APP_DIR" >&2
    printf "  - %s\n" "${missing[@]}" >&2
    exit 1
  fi
}

install_backend_runtime() {
  echo "[supervisor-install] Preparing backend Python runtime"
  cd "$APP_DIR/backend"
  python3 -m venv .venv
  # shellcheck source=/dev/null
  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  deactivate
}

install_tmpfiles_rule() {
  local src="$APP_DIR/systemd/tmpfiles.d/hexe.conf"
  local dst="/etc/tmpfiles.d/hexe.conf"

  if [[ ! -f "$src" ]]; then
    echo "[supervisor-install] WARN: missing tmpfiles rule at $src"
    return 0
  fi

  if need_cmd sudo; then
    echo "[supervisor-install] Installing /run/hexe tmpfiles rule"
    sudo install -m 0644 "$src" "$dst" || true
    sudo systemd-tmpfiles --create "$dst" || true
  else
    echo "[supervisor-install] WARN: sudo unavailable; /run/hexe must be created manually"
  fi
}

exchange_enrollment_token() {
  if [[ "$INSTALL_MODE" != "join-core" || -z "$ENROLLMENT_TOKEN" ]]; then
    return 0
  fi

  echo "[supervisor-install] Exchanging one-time enrollment token with Core"
  CORE_TOKEN="$(
    CORE_URL="$CORE_URL" \
    ENROLLMENT_TOKEN="$ENROLLMENT_TOKEN" \
    SUPERVISOR_ID="$SUPERVISOR_ID" \
    SUPERVISOR_NAME="$SUPERVISOR_NAME" \
    SUPERVISOR_PUBLIC_URL="$SUPERVISOR_PUBLIC_URL" \
    python3 - <<'PY'
import json
import os
import socket
import sys
import urllib.error
import urllib.request

core_url = os.environ["CORE_URL"].rstrip("/")
payload = {
    "enrollment_token": os.environ["ENROLLMENT_TOKEN"],
    "supervisor_id": os.environ["SUPERVISOR_ID"],
    "supervisor_name": os.environ.get("SUPERVISOR_NAME") or os.environ["SUPERVISOR_ID"],
    "hostname": socket.gethostname(),
    "host_id": socket.gethostname(),
    "api_base_url": os.environ.get("SUPERVISOR_PUBLIC_URL") or None,
    "transport": "socket",
    "capabilities": [
        "host_resources",
        "runtime_inventory",
        "node_runtime_registry",
        "core_runtime_registry",
    ],
    "metadata": {"installer": "scripts/supervisor_install.sh"},
}
request = urllib.request.Request(
    f"{core_url}/api/system/supervisors/enroll",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    print(f"[supervisor-install] enrollment failed: HTTP {exc.code} {detail}", file=sys.stderr)
    sys.exit(1)
except Exception as exc:
    print(f"[supervisor-install] enrollment failed: {exc}", file=sys.stderr)
    sys.exit(1)

reporting_token = str(data.get("reporting_token") or "").strip()
if not reporting_token:
    print("[supervisor-install] enrollment response did not include reporting_token", file=sys.stderr)
    sys.exit(1)
print(reporting_token)
PY
  )"
  CORE_TOKEN_KIND="supervisor"
  ENROLLMENT_TOKEN=""
}

env_value() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "$value"
}

write_env_if_set() {
  local key="$1"
  local value="$2"
  if [[ -n "$value" ]]; then
    printf "%s=%s\n" "$key" "$(env_value "$value")"
  fi
}

write_supervisor_env() {
  if [[ -z "$INSTALL_MODE" && -z "$CORE_URL" && -z "$SUPERVISOR_ID" && -z "$SUPERVISOR_NAME" && -z "$SUPERVISOR_PUBLIC_URL" ]]; then
    return 0
  fi

  echo "[supervisor-install] Writing Supervisor config"
  mkdir -p "$HOME/.config/hexe"
  local env_file="$HOME/.config/hexe/supervisor.env"
  {
    write_env_if_set "HEXE_SUPERVISOR_INSTALL_MODE" "$INSTALL_MODE"
    write_env_if_set "HEXE_SUPERVISOR_CORE_URL" "$CORE_URL"
    write_env_if_set "HEXE_SUPERVISOR_CORE_TOKEN" "$CORE_TOKEN"
    write_env_if_set "HEXE_SUPERVISOR_CORE_TOKEN_KIND" "$CORE_TOKEN_KIND"
    write_env_if_set "HEXE_SUPERVISOR_ID" "$SUPERVISOR_ID"
    write_env_if_set "HEXE_SUPERVISOR_NAME" "$SUPERVISOR_NAME"
    write_env_if_set "HEXE_SUPERVISOR_PUBLIC_URL" "$SUPERVISOR_PUBLIC_URL"
    write_env_if_set "HEXE_SUPERVISOR_REPORT_INTERVAL_S" "$REPORT_INTERVAL_S"
    if [[ -n "$CORE_URL" ]]; then
      printf "HEXE_SUPERVISOR_REPORT_ENABLED=true\n"
    else
      printf "HEXE_SUPERVISOR_REPORT_ENABLED=false\n"
    fi
  } > "$env_file"
  chmod 600 "$env_file"

  if [[ -n "$CORE_URL" && -z "$CORE_TOKEN" ]]; then
    echo "[supervisor-install] WARN: --core-url was provided without a reporting token; remote reporting will not authenticate."
  fi
}

install_unit() {
  local template="$1"
  local out="$2"

  if [[ ! -f "$template" ]]; then
    echo "[supervisor-install] ERROR: missing unit template: $template" >&2
    exit 1
  fi

  sed "s|@INSTALL_DIR@|$APP_DIR|g" "$template" > "$out"
}

install_user_units() {
  local unit_src_dir="$APP_DIR/systemd/user"
  local unit_dst_dir="$HOME/.config/systemd/user"

  echo "[supervisor-install] Installing Supervisor systemd user units"
  mkdir -p "$unit_dst_dir"
  install_unit "$unit_src_dir/hexe-supervisor.service.in" "$unit_dst_dir/hexe-supervisor.service"
  install_unit "$unit_src_dir/hexe-supervisor-api.service.in" "$unit_dst_dir/hexe-supervisor-api.service"
  systemctl --user daemon-reload
}

start_user_units() {
  echo "[supervisor-install] Enabling and starting Supervisor services"
  systemctl --user enable --now hexe-supervisor.service
  systemctl --user enable --now hexe-supervisor-api.service
}

curl_supervisor_health() {
  curl -fsS --unix-socket "$SUPERVISOR_SOCKET" "http://localhost/health"
}

wait_for_supervisor_api() {
  echo "[supervisor-install] Waiting for Supervisor API at unix://$SUPERVISOR_SOCKET"
  for _ in {1..30}; do
    if curl_supervisor_health >/dev/null 2>&1; then
      echo "[supervisor-install] Supervisor API is healthy"
      return 0
    fi
    sleep 1
  done

  echo "[supervisor-install] ERROR: Supervisor API did not become healthy." >&2
  systemctl --user status hexe-supervisor-api.service --no-pager || true
  return 1
}

echo "[supervisor-install] install_mode=$INSTALL_MODE"
echo "[supervisor-install] install_dir=$INSTALL_DIR"
echo "[supervisor-install] repo_url=$REPO_URL branch=$BRANCH"

ensure_deps
clone_or_refresh_repo
resolve_app_dir
echo "[supervisor-install] app_dir=$APP_DIR"
ensure_repo_layout
install_backend_runtime
install_tmpfiles_rule
exchange_enrollment_token
write_supervisor_env
install_user_units

if [[ "$START_SERVICES" == "true" ]]; then
  start_user_units
  wait_for_supervisor_api
else
  echo "[supervisor-install] Installed units without starting services."
fi

echo "[supervisor-install] Host Supervisor install complete."

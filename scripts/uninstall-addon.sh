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

CORE_URL="${SYNTHIA_CORE_URL:-http://127.0.0.1:9001}"
ADMIN_TOKEN_OVERRIDE=""
FORCE_LOCAL=false
ADDON_ID=""

usage() {
  cat <<EOF
Usage:
  scripts/uninstall-addon.sh <addon_id> [--core-url URL] [--admin-token TOKEN] [--force-local]

Options:
  --core-url URL       Core API base URL (default: ${CORE_URL})
  --admin-token TOKEN  Override SYNTHIA_ADMIN_TOKEN for this run
  --force-local        If API uninstall fails, remove local standalone files/containers
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --core-url)
      CORE_URL="${2:-}"
      shift 2
      ;;
    --admin-token)
      ADMIN_TOKEN_OVERRIDE="${2:-}"
      shift 2
      ;;
    --force-local)
      FORCE_LOCAL=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "$ADDON_ID" ]]; then
        ADDON_ID="$1"
        shift
      else
        echo "[uninstall-addon] Unknown arg: $1" >&2
        usage
        exit 1
      fi
      ;;
  esac
done

if [[ -z "$ADDON_ID" ]]; then
  usage
  exit 1
fi

ADMIN_TOKEN="${ADMIN_TOKEN_OVERRIDE:-${SYNTHIA_ADMIN_TOKEN:-}}"
COOKIE_JAR="/tmp/synthia_uninstall_cookie_$$.txt"
trap 'rm -f "$COOKIE_JAR"' EXIT

http_code_and_body() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  shift 3 || true
  local extra=("$@")
  if [[ -n "$body" ]]; then
    curl -sS -w $'\n%{http_code}' -X "$method" "$url" "${extra[@]}" -H "Content-Type: application/json" -d "$body"
  else
    curl -sS -w $'\n%{http_code}' -X "$method" "$url" "${extra[@]}"
  fi
}

attempt_uninstall_with_token() {
  if [[ -z "$ADMIN_TOKEN" ]]; then
    return 1
  fi
  local response body code
  response="$(http_code_and_body POST "${CORE_URL%/}/api/store/uninstall" "{\"addon_id\":\"$ADDON_ID\"}" -H "X-Admin-Token: ${ADMIN_TOKEN}")"
  body="$(printf "%s\n" "$response" | sed '$d')"
  code="$(printf "%s\n" "$response" | tail -n1)"
  if [[ "$code" == "200" ]]; then
    echo "[uninstall-addon] API uninstall succeeded (token auth)."
    echo "$body"
    return 0
  fi
  echo "[uninstall-addon] API uninstall with token failed (HTTP $code)." >&2
  echo "[uninstall-addon] Response: $body" >&2
  return 1
}

attempt_uninstall_with_session() {
  local login_payload
  if [[ -n "${SYNTHIA_ADMIN_USERNAME:-}" && -n "${SYNTHIA_ADMIN_PASSWORD:-}" ]]; then
    login_payload="{\"username\":\"${SYNTHIA_ADMIN_USERNAME}\",\"password\":\"${SYNTHIA_ADMIN_PASSWORD}\"}"
  elif [[ -n "$ADMIN_TOKEN" ]]; then
    login_payload="{\"token\":\"${ADMIN_TOKEN}\"}"
  else
    return 1
  fi

  local login_response login_body login_code
  login_response="$(http_code_and_body POST "${CORE_URL%/}/api/admin/session/login" "$login_payload" -c "$COOKIE_JAR")"
  login_body="$(printf "%s\n" "$login_response" | sed '$d')"
  login_code="$(printf "%s\n" "$login_response" | tail -n1)"
  if [[ "$login_code" != "200" ]]; then
    echo "[uninstall-addon] Admin session login failed (HTTP $login_code)." >&2
    echo "[uninstall-addon] Response: $login_body" >&2
    return 1
  fi

  local uninstall_response uninstall_body uninstall_code
  uninstall_response="$(http_code_and_body POST "${CORE_URL%/}/api/store/uninstall" "{\"addon_id\":\"$ADDON_ID\"}" -b "$COOKIE_JAR")"
  uninstall_body="$(printf "%s\n" "$uninstall_response" | sed '$d')"
  uninstall_code="$(printf "%s\n" "$uninstall_response" | tail -n1)"
  if [[ "$uninstall_code" == "200" ]]; then
    echo "[uninstall-addon] API uninstall succeeded (session auth)."
    echo "$uninstall_body"
    return 0
  fi
  echo "[uninstall-addon] API uninstall with session failed (HTTP $uninstall_code)." >&2
  echo "[uninstall-addon] Response: $uninstall_body" >&2
  return 1
}

resolve_addons_dir() {
  local raw="${SYNTHIA_ADDONS_DIR:-../SynthiaAddons}"
  if [[ "$raw" = /* ]]; then
    realpath -m "$raw"
  else
    realpath -m "$REPO_DIR/$raw"
  fi
}

force_local_cleanup() {
  echo "[uninstall-addon] Running local fallback cleanup for '$ADDON_ID'..."

  local project="synthia-addon-${ADDON_ID}"
  mapfile -t ids_by_label < <(docker ps -a --filter "label=com.docker.compose.project=${project}" --format '{{.ID}}' || true)
  mapfile -t ids_by_name < <(docker ps -a --format '{{.ID}}\t{{.Names}}' | awk -v pfx="${project}" '$2 ~ "^" pfx {print $1}')
  mapfile -t container_ids < <(printf "%s\n%s\n" "${ids_by_label[*]:-}" "${ids_by_name[*]:-}" | tr ' ' '\n' | sed '/^$/d' | sort -u)

  if (( ${#container_ids[@]} > 0 )); then
    docker rm -f "${container_ids[@]}" >/dev/null
    echo "[uninstall-addon] Removed ${#container_ids[@]} local container(s)."
  else
    echo "[uninstall-addon] No local synthia-addon containers found for '$ADDON_ID'."
  fi

  local addons_dir service_dir
  addons_dir="$(resolve_addons_dir)"
  service_dir="$addons_dir/services/$ADDON_ID"
  if [[ -d "$service_dir" || -L "$service_dir" ]]; then
    find "$service_dir" -type f -delete 2>/dev/null || true
    find "$service_dir" -type l -delete 2>/dev/null || true
    find "$service_dir" -depth -type d -empty -delete 2>/dev/null || true
    if [[ -e "$service_dir" ]]; then
      echo "[uninstall-addon] WARNING: service dir still exists: $service_dir" >&2
      return 1
    fi
    echo "[uninstall-addon] Removed local service dir: $service_dir"
  else
    echo "[uninstall-addon] Service dir not found: $service_dir"
  fi
}

if attempt_uninstall_with_token; then
  exit 0
fi

if attempt_uninstall_with_session; then
  exit 0
fi

if [[ "$FORCE_LOCAL" == "true" ]]; then
  force_local_cleanup
  exit 0
fi

echo "[uninstall-addon] Uninstall failed via API auth paths. Re-run with --force-local for local cleanup fallback." >&2
exit 1

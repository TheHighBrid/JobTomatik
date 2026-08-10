#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
BACKEND_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd -- "$BACKEND_ROOT/.." && pwd)"
FRONTEND_ROOT="${JOBTOMATIK_FRONTEND_ROOT:-$REPO_ROOT/frontend}"
RUNTIME_DIR="${JOBTOMATIK_RUNTIME_DIR:-$BACKEND_ROOT/.runtime}"
VENV="${JOBTOMATIK_BACKEND_VENV:-$BACKEND_ROOT/.venv}"
BEAT_SCHEDULE="$RUNTIME_DIR/celerybeat-schedule"

# shellcheck source=jobtomatik_process_identity.sh
source "$SCRIPT_DIR/jobtomatik_process_identity.sh"

pid_identity_matches() {
  local role="$1"
  local pid="$2"
  case "$role" in
    api)
      jobtomatik_pid_has_all_tokens "$pid" "$VENV/bin/uvicorn" "app.main:app" "--port" "8010"
      ;;
    worker)
      jobtomatik_pid_has_all_tokens "$pid" "$VENV/bin/celery" "-A" "app.celery_app" "worker" "jobtomatik-android-"
      ;;
    beat)
      jobtomatik_pid_has_all_tokens "$pid" "$VENV/bin/celery" "-A" "app.celery_app" "beat" "$BEAT_SCHEDULE"
      ;;
    frontend)
      jobtomatik_pid_has_all_tokens "$pid" "npm" "run dev" "--port" "3000" \
        && jobtomatik_pid_cwd_is "$pid" "$FRONTEND_ROOT"
      ;;
    *)
      return 2
      ;;
  esac
}

sanitize_pid_file() {
  local role="$1"
  local pid_file="$2"
  [[ -f "$pid_file" ]] || return 0

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
    rm -f "$pid_file"
    echo "ANDROID_STALE_PID_REJECTED role=$role pid=invalid action=pid_file_removed_process_not_signaled"
    return 0
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    echo "ANDROID_STALE_PID_REJECTED role=$role pid=$pid action=dead_pid_file_removed"
    return 0
  fi

  if pid_identity_matches "$role" "$pid"; then
    echo "ANDROID_MANAGED_PID_VERIFIED role=$role pid=$pid"
    return 0
  fi

  rm -f "$pid_file"
  echo "ANDROID_STALE_PID_REJECTED role=$role pid=$pid action=pid_file_removed_process_not_signaled"
}

mkdir -p "$RUNTIME_DIR"
sanitize_pid_file frontend "$RUNTIME_DIR/frontend.pid"
sanitize_pid_file beat "$RUNTIME_DIR/celery-beat.pid"
sanitize_pid_file worker "$RUNTIME_DIR/celery.pid"
sanitize_pid_file api "$RUNTIME_DIR/api.pid"
echo "ANDROID_RUNTIME_PID_FILES_SANITIZED"

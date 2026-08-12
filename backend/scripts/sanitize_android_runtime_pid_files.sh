#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
BACKEND_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd -- "$BACKEND_ROOT/.." && pwd)"
FRONTEND_ROOT="${JOBTOMATIK_FRONTEND_ROOT:-$REPO_ROOT/frontend}"
RUNTIME_DIR="${JOBTOMATIK_RUNTIME_DIR:-$BACKEND_ROOT/.runtime}"
VENV="${JOBTOMATIK_BACKEND_VENV:-$BACKEND_ROOT/.venv}"
BEAT_SCHEDULE="$RUNTIME_DIR/celerybeat-schedule"
RUNTIME_REVISION="${JOBTOMATIK_RUNTIME_REVISION:-$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)}"
FRONTEND_ARTIFACT_ROOT="${JOBTOMATIK_FRONTEND_ARTIFACT_ROOT:-$RUNTIME_DIR/frontend-artifacts/$RUNTIME_REVISION}"
FRONTEND_ARTIFACTS_ROOT="$(dirname -- "$FRONTEND_ARTIFACT_ROOT")"
STATIC_FRONTEND_SERVER="$BACKEND_ROOT/scripts/serve_static_frontend.py"

# shellcheck source=jobtomatik_process_identity.sh
source "$SCRIPT_DIR/jobtomatik_process_identity.sh"

frontend_static_identity_matches() {
  local pid="$1"
  jobtomatik_static_frontend_pid_matches \
    "$pid" \
    "$VENV/bin/python" \
    "$STATIC_FRONTEND_SERVER" \
    "$FRONTEND_ARTIFACTS_ROOT"
}

frontend_legacy_vite_identity_matches() {
  local pid="$1"
  jobtomatik_pid_has_all_tokens "$pid" "npm" "run dev" "--port" "3000" \
    && jobtomatik_pid_cwd_is "$pid" "$FRONTEND_ROOT"
}

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
      frontend_static_identity_matches "$pid" || frontend_legacy_vite_identity_matches "$pid"
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

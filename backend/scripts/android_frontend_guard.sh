#!/usr/bin/env bash
set -euo pipefail

BACKEND_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
REPO_ROOT="$(cd -- "$BACKEND_ROOT/.." && pwd)"
FRONTEND_ROOT="${JOBTOMATIK_FRONTEND_ROOT:-$REPO_ROOT/frontend}"
RUNTIME_DIR="${JOBTOMATIK_RUNTIME_DIR:-$BACKEND_ROOT/.runtime}"
VENV="${JOBTOMATIK_BACKEND_VENV:-$BACKEND_ROOT/.venv}"
PROC_ROOT="${JOBTOMATIK_PROC_ROOT:-/proc}"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
MODE="${1:-status}"
FRONTEND_URL="${JOBTOMATIK_FRONTEND_URL:-http://127.0.0.1:3000}"
RUNTIME_REVISION="${JOBTOMATIK_RUNTIME_REVISION:-$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)}"
FRONTEND_ARTIFACT_ROOT="${JOBTOMATIK_FRONTEND_ARTIFACT_ROOT:-$RUNTIME_DIR/frontend-artifacts/$RUNTIME_REVISION}"
FRONTEND_DIST_ROOT="$FRONTEND_ARTIFACT_ROOT/dist"
FRONTEND_MANIFEST="$FRONTEND_ARTIFACT_ROOT/jobtomatik-frontend-manifest.json"
STATIC_FRONTEND_SERVER="$BACKEND_ROOT/scripts/serve_static_frontend.py"
PROCESS_IDENTITY_HELPER="$BACKEND_ROOT/scripts/jobtomatik_process_identity.sh"

if [[ ! -r "$PROCESS_IDENTITY_HELPER" ]]; then
  echo "JobTomatik process identity helper is missing: $PROCESS_IDENTITY_HELPER" >&2
  exit 1
fi
# shellcheck source=jobtomatik_process_identity.sh
source "$PROCESS_IDENTITY_HELPER"

http_ready() {
  curl -fsS --max-time 2 "$FRONTEND_URL" >/dev/null 2>&1
}

pid_file_value() {
  cat "$FRONTEND_PID_FILE" 2>/dev/null || true
}

pid_file_alive() {
  [[ -f "$FRONTEND_PID_FILE" ]] || return 1
  local pid
  pid="$(pid_file_value)"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}

static_pid_matches() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null || return 1
  jobtomatik_pid_has_all_tokens \
    "$pid" \
    "$VENV/bin/python" \
    "$STATIC_FRONTEND_SERVER" \
    "--root" \
    "$FRONTEND_DIST_ROOT" \
    "--manifest" \
    "$FRONTEND_MANIFEST" \
    "--revision" \
    "$RUNTIME_REVISION" \
    "--port" \
    "3000"
}

legacy_vite_pid_matches() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null || return 1
  jobtomatik_pid_has_all_tokens "$pid" "vite" "--port" "3000" \
    && {
      jobtomatik_pid_cwd_is "$pid" "$FRONTEND_ROOT" \
        || [[ "$(jobtomatik_proc_cmdline "$pid" 2>/dev/null || true)" == *"$FRONTEND_ROOT/"* ]]
    }
}

identity_ready() {
  [[ -x "$VENV/bin/python" ]] || return 1
  [[ -f "$FRONTEND_MANIFEST" ]] || return 1
  curl -fsS --max-time 2 "$FRONTEND_URL/__jobtomatik_frontend_identity" 2>/dev/null | \
    JOBTOMATIK_EXPECTED_FRONTEND_REVISION="$RUNTIME_REVISION" \
    JOBTOMATIK_FRONTEND_MANIFEST="$FRONTEND_MANIFEST" \
    "$VENV/bin/python" -c '
import json
import os
import sys
from pathlib import Path

payload = json.load(sys.stdin)
manifest = json.loads(Path(os.environ["JOBTOMATIK_FRONTEND_MANIFEST"]).read_text(encoding="utf-8"))
valid = (
    payload.get("ok") is True
    and payload.get("runtime") == "static_artifact"
    and payload.get("revision") == os.environ["JOBTOMATIK_EXPECTED_FRONTEND_REVISION"]
    and payload.get("revision") == manifest.get("revision")
    and payload.get("dist_tree_sha256") == manifest.get("dist_tree_sha256")
    and payload.get("package_lock_sha256") == manifest.get("package_lock_sha256")
    and payload.get("final_submit_allowed") is False
    and payload.get("outreach_authorized") is False
)
raise SystemExit(0 if valid else 1)
' >/dev/null 2>&1
}

managed_ready() {
  pid_file_alive || return 1
  local pid
  pid="$(pid_file_value)"
  static_pid_matches "$pid" && http_ready && identity_ready
}

identified_frontend_pids() {
  local proc pid
  for proc in "$PROC_ROOT"/[0-9]*; do
    [[ -r "$proc/cmdline" ]] || continue
    pid="${proc##*/}"
    [[ "$pid" != "$$" ]] || continue
    if static_pid_matches "$pid" || legacy_vite_pid_matches "$pid"; then
      printf '%s\n' "$pid"
    fi
  done
}

stop_identified_frontend() {
  local label="$1"
  local candidates=()
  mapfile -t candidates < <(identified_frontend_pids)

  if [[ "${#candidates[@]}" -eq 0 ]]; then
    if http_ready; then
      echo "ANDROID_FRONTEND_UNMANAGED_PORT_3000" >&2
      echo "Port 3000 is reachable, but no narrowly identifiable JobTomatik frontend process owns it." >&2
      return 1
    fi
    rm -f "$FRONTEND_PID_FILE"
    echo "ANDROID_FRONTEND_PORT_3000_CLEAR"
    return 0
  fi

  local pid
  for pid in "${candidates[@]}"; do
    if static_pid_matches "$pid" || legacy_vite_pid_matches "$pid"; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done

  for _ in {1..40}; do
    if ! http_ready; then
      rm -f "$FRONTEND_PID_FILE"
      echo "${label} pids=${candidates[*]}"
      return 0
    fi
    sleep 0.25
  done

  echo "ANDROID_FRONTEND_PROCESS_STILL_LISTENING pids=${candidates[*]}" >&2
  return 1
}

retire_unmanaged() {
  if ! http_ready; then
    rm -f "$FRONTEND_PID_FILE"
    echo "ANDROID_FRONTEND_PORT_3000_CLEAR"
    return 0
  fi

  if managed_ready; then
    echo "ANDROID_FRONTEND_STATIC_MANAGED_READY pid=$(pid_file_value) revision=$RUNTIME_REVISION"
    return 0
  fi

  stop_identified_frontend "ANDROID_FRONTEND_UNMANAGED_JOBTOMATIK_RETIRED"
}

reset_frontend() {
  if ! http_ready; then
    rm -f "$FRONTEND_PID_FILE"
    echo "ANDROID_FRONTEND_PORT_3000_CLEAR"
    return 0
  fi
  stop_identified_frontend "ANDROID_FRONTEND_EXISTING_JOBTOMATIK_RETIRED"
}

case "$MODE" in
  status)
    if managed_ready; then
      echo "ANDROID_FRONTEND_STATIC_MANAGED_READY pid=$(pid_file_value) revision=$RUNTIME_REVISION"
      exit 0
    fi
    if http_ready; then
      echo "ANDROID_FRONTEND_READY_BUT_UNMANAGED_OR_UNATTESTED"
    else
      echo "ANDROID_FRONTEND_DOWN"
    fi
    exit 1
    ;;
  retire)
    retire_unmanaged
    ;;
  reset)
    reset_frontend
    ;;
  *)
    echo "Usage: $0 [status|retire|reset]" >&2
    exit 2
    ;;
esac

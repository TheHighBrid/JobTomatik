#!/usr/bin/env bash
set -euo pipefail

BACKEND_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
REPO_ROOT="$(cd -- "$BACKEND_ROOT/.." && pwd)"
FRONTEND_ROOT="$REPO_ROOT/frontend"
RUNTIME_DIR="$BACKEND_ROOT/.runtime"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
MODE="${1:-status}"
FRONTEND_URL="http://127.0.0.1:3000"

http_ready() {
  curl -fsS --max-time 2 "$FRONTEND_URL" >/dev/null 2>&1
}

pid_file_alive() {
  [[ -f "$FRONTEND_PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$FRONTEND_PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

managed_ready() {
  pid_file_alive && http_ready
}

jobtomatik_vite_pids() {
  local proc pid cwd cmdline
  for proc in /proc/[0-9]*; do
    [[ -r "$proc/cmdline" ]] || continue
    pid="${proc##*/}"
    [[ "$pid" != "$$" ]] || continue
    cwd="$(readlink "$proc/cwd" 2>/dev/null || true)"
    [[ "$cwd" == "$FRONTEND_ROOT" ]] || continue
    cmdline="$(tr '\0' ' ' < "$proc/cmdline" 2>/dev/null || true)"
    [[ "$cmdline" == *"vite"* ]] || continue
    [[ "$cmdline" == *"--port 3000"* || "$cmdline" == *"--port=3000"* ]] || continue
    printf '%s\n' "$pid"
  done
}

stop_identified_vite() {
  local label="$1"
  local candidates=()
  mapfile -t candidates < <(jobtomatik_vite_pids)

  if [[ "${#candidates[@]}" -eq 0 ]]; then
    if http_ready; then
      echo "ANDROID_FRONTEND_UNMANAGED_PORT_3000" >&2
      echo "Port 3000 is reachable, but no narrowly identifiable JobTomatik Vite process owns it." >&2
      return 1
    fi
    rm -f "$FRONTEND_PID_FILE"
    echo "ANDROID_FRONTEND_PORT_3000_CLEAR"
    return 0
  fi

  local pid
  for pid in "${candidates[@]}"; do
    kill -TERM "$pid" 2>/dev/null || true
  done

  for _ in {1..40}; do
    if ! http_ready; then
      rm -f "$FRONTEND_PID_FILE"
      echo "${label} pids=${candidates[*]}"
      return 0
    fi
    sleep 0.25
  done

  echo "ANDROID_FRONTEND_VITE_STILL_LISTENING pids=${candidates[*]}" >&2
  return 1
}

retire_unmanaged() {
  if ! http_ready; then
    rm -f "$FRONTEND_PID_FILE"
    echo "ANDROID_FRONTEND_PORT_3000_CLEAR"
    return 0
  fi

  if managed_ready; then
    echo "ANDROID_FRONTEND_MANAGED_READY pid=$(cat "$FRONTEND_PID_FILE")"
    return 0
  fi

  stop_identified_vite "ANDROID_FRONTEND_UNMANAGED_VITE_RETIRED"
}

reset_frontend() {
  if ! http_ready; then
    rm -f "$FRONTEND_PID_FILE"
    echo "ANDROID_FRONTEND_PORT_3000_CLEAR"
    return 0
  fi
  stop_identified_vite "ANDROID_FRONTEND_EXISTING_VITE_RETIRED"
}

case "$MODE" in
  status)
    if managed_ready; then
      echo "ANDROID_FRONTEND_MANAGED_READY pid=$(cat "$FRONTEND_PID_FILE")"
      exit 0
    fi
    if http_ready; then
      echo "ANDROID_FRONTEND_READY_BUT_UNMANAGED"
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

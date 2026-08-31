#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ACTION="${1:-status}"
RUNTIME_DIR="${JOBTOMATIK_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"
PID_FILE="$RUNTIME_DIR/pilot-controller.pid"
LOG_FILE="$RUNTIME_DIR/pilot-controller.log"
DAEMON_COMMAND="${JOBTOMATIK_PILOT_CONTROLLER_COMMAND:-jobtomatik-pilot-controller}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PROCESS_IDENTITY_HELPER="${JOBTOMATIK_PROCESS_IDENTITY_HELPER:-$SCRIPT_DIR/jobtomatik_process_identity.sh}"

if [[ ! -r "$PROCESS_IDENTITY_HELPER" ]]; then
  echo "JobTomatik pilot controller identity helper is missing: $PROCESS_IDENTITY_HELPER" >&2
  exit 1
fi
# shellcheck source=jobtomatik_process_identity.sh
source "$PROCESS_IDENTITY_HELPER"

mkdir -p "$RUNTIME_DIR"

controller_identity_matches() {
  local pid="$1"
  jobtomatik_pid_has_all_tokens "$pid" "jobtomatik-pilot-controller"
}

controller_alive() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  controller_identity_matches "$pid"
}

start_controller() {
  if controller_alive; then
    echo "JOBTOMATIK_PILOT_CONTROLLER_READY pid=$(cat "$PID_FILE")"
    return 0
  fi

  if [[ -f "$PID_FILE" ]]; then
    local stale_pid
    stale_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$stale_pid" ]] && kill -0 "$stale_pid" 2>/dev/null; then
      echo "JOBTOMATIK_STALE_PILOT_CONTROLLER_PID_REJECTED pid=$stale_pid action=not_signaled" >&2
    fi
    rm -f "$PID_FILE"
  fi

  : > "$LOG_FILE"
  nohup "$DAEMON_COMMAND" >> "$LOG_FILE" 2>&1 </dev/null &
  local pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"

  for _ in {1..15}; do
    if kill -0 "$pid" 2>/dev/null && controller_identity_matches "$pid"; then
      echo "JOBTOMATIK_PILOT_CONTROLLER_READY pid=$pid"
      return 0
    fi
    sleep 1
  done

  rm -f "$PID_FILE"
  echo "JOBTOMATIK_PILOT_CONTROLLER_START_FAILED" >&2
  tail -n 80 "$LOG_FILE" >&2 || true
  return 1
}

stop_controller() {
  if [[ ! -f "$PID_FILE" ]]; then
    echo "JOBTOMATIK_PILOT_CONTROLLER_STOPPED"
    return 0
  fi

  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    if controller_identity_matches "$pid"; then
      jobtomatik_signal_if_identity TERM "$pid" "jobtomatik-pilot-controller" || true
      for _ in {1..10}; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
      done
      if kill -0 "$pid" 2>/dev/null && controller_identity_matches "$pid"; then
        jobtomatik_signal_if_identity KILL "$pid" "jobtomatik-pilot-controller" || true
      fi
    else
      echo "JOBTOMATIK_STALE_PILOT_CONTROLLER_PID_REJECTED pid=$pid action=not_signaled" >&2
    fi
  fi
  rm -f "$PID_FILE"
  echo "JOBTOMATIK_PILOT_CONTROLLER_STOPPED"
}

case "$ACTION" in
  start)
    start_controller
    ;;
  stop)
    stop_controller
    ;;
  restart)
    stop_controller
    start_controller
    ;;
  status)
    if controller_alive; then
      echo "JOBTOMATIK_PILOT_CONTROLLER_READY pid=$(cat "$PID_FILE")"
    else
      echo "JOBTOMATIK_PILOT_CONTROLLER_DOWN" >&2
      exit 1
    fi
    ;;
  *)
    echo "Usage: jobtomatik-pilot-controller-manager [start|stop|restart|status]" >&2
    exit 2
    ;;
esac

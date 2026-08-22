#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

PROFILE_DIR="${JOBTOMATIK_ANDROID_BROWSER_PROFILE:-$HOME/.jobtomatik-chromium}"
CDP_PORT="${JOBTOMATIK_ANDROID_BROWSER_PORT:-9222}"
DISPLAY_VALUE="${DISPLAY:-:0}"
BROWSER_BIN="${JOBTOMATIK_ANDROID_BROWSER_BIN:-$(command -v chromium-browser || true)}"
RUNTIME_DIR="${JOBTOMATIK_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"
SUPERVISOR_PID_FILE="$RUNTIME_DIR/chromium-supervisor.pid"
BROWSER_PID_FILE="$RUNTIME_DIR/chromium-browser.pid"
STOP_FILE="$RUNTIME_DIR/chromium-supervisor.stop"
SUPERVISOR_LOG="$RUNTIME_DIR/chromium-supervisor.log"
BROWSER_LOG="$RUNTIME_DIR/chromium.log"
DEFAULT_URL="https://www.linkedin.com/feed/"
SCRIPT_PATH="$(cd -- "$(dirname -- "$0")" && pwd)/$(basename -- "$0")"
SCRIPT_DIR="$(dirname -- "$SCRIPT_PATH")"
PROCESS_IDENTITY_HELPER="${JOBTOMATIK_PROCESS_IDENTITY_HELPER:-$SCRIPT_DIR/jobtomatik_process_identity.sh}"
MAX_LOG_BYTES="${JOBTOMATIK_ANDROID_MAX_LOG_BYTES:-5242880}"

if [[ ! -r "$PROCESS_IDENTITY_HELPER" ]]; then
  echo "JobTomatik Android process-identity helper is missing: $PROCESS_IDENTITY_HELPER" >&2
  exit 1
fi
# shellcheck source=jobtomatik_process_identity.sh
source "$PROCESS_IDENTITY_HELPER"

ACTION="${1:-start}"
case "$ACTION" in
  start|stop|restart|recover|status|foreground|supervise)
    shift || true
    ;;
  http://*|https://*)
    DEFAULT_URL="$ACTION"
    ACTION="start"
    shift || true
    ;;
  *)
    echo "Usage: $0 [start|stop|restart|recover|status|foreground] [url]" >&2
    exit 2
    ;;
esac
START_URL="${1:-$DEFAULT_URL}"

mkdir -p "$PROFILE_DIR" "$RUNTIME_DIR"
export DISPLAY="$DISPLAY_VALUE"

if [[ -z "$BROWSER_BIN" ]]; then
  echo "chromium-browser was not found in native Termux." >&2
  echo "Install it with: pkg install x11-repo chromium" >&2
  exit 1
fi

cdp_url() {
  printf 'http://127.0.0.1:%s/json/version' "$CDP_PORT"
}

is_healthy() {
  curl -fsS --max-time 2 "$(cdp_url)" 2>/dev/null | grep -q 'webSocketDebuggerUrl'
}

rotate_log() {
  local log_file="$1"
  if [[ -f "$log_file" ]]; then
    local size
    size="$(wc -c < "$log_file" 2>/dev/null || echo 0)"
    if (( size >= MAX_LOG_BYTES )); then
      rm -f "$log_file.1"
      mv "$log_file" "$log_file.1"
    fi
  fi
}

browser_command() {
  exec "$BROWSER_BIN" \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --disable-features=Vulkan,WebGPU \
    --ozone-platform=x11 \
    --no-first-run \
    --no-default-browser-check \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port="$CDP_PORT" \
    --user-data-dir="$PROFILE_DIR" \
    "$START_URL"
}

wait_for_health() {
  local attempts="${1:-60}"
  local index
  for ((index = 0; index < attempts; index += 1)); do
    if is_healthy; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

supervisor_identity_matches() {
  local pid="$1"
  jobtomatik_pid_has_all_tokens "$pid" "$SCRIPT_PATH" "supervise"
}

browser_identity_matches() {
  local pid="$1"
  jobtomatik_pid_has_all_tokens \
    "$pid" \
    "--remote-debugging-port=$CDP_PORT" \
    "--user-data-dir=$PROFILE_DIR"
}

managed_browser_pids() {
  local candidate=""
  local emitted=""

  if [[ -f "$BROWSER_PID_FILE" ]]; then
    candidate="$(cat "$BROWSER_PID_FILE" 2>/dev/null || true)"
    if [[ -n "$candidate" ]] && kill -0 "$candidate" 2>/dev/null && browser_identity_matches "$candidate"; then
      printf '%s\n' "$candidate"
      emitted="$candidate"
    fi
  fi

  while read -r candidate; do
    [[ -n "$candidate" ]] || continue
    [[ "$candidate" != "$emitted" ]] || continue
    if kill -0 "$candidate" 2>/dev/null && browser_identity_matches "$candidate"; then
      printf '%s\n' "$candidate"
    fi
  done < <(pgrep -f "remote-debugging-port=${CDP_PORT}" 2>/dev/null || true)
}

signal_browser_if_managed() {
  local signal_name="$1"
  local pid="$2"
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  if browser_identity_matches "$pid"; then
    jobtomatik_signal_if_identity \
      "$signal_name" \
      "$pid" \
      "--remote-debugging-port=$CDP_PORT" \
      "--user-data-dir=$PROFILE_DIR" || true
    return 0
  fi
  echo "ANDROID_BROWSER_STALE_BROWSER_PID_REJECTED pid=$pid action=not_signaled" >&2
}

stop_browser_processes() {
  local signal_name="${1:-TERM}"
  local pid
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    signal_browser_if_managed "$signal_name" "$pid"
  done < <(managed_browser_pids)
}

wait_for_shutdown() {
  local supervisor_pid="${1:-}"
  local index
  for ((index = 0; index < 40; index += 1)); do
    local supervisor_gone=true
    if [[ -n "$supervisor_pid" ]] \
      && kill -0 "$supervisor_pid" 2>/dev/null \
      && supervisor_identity_matches "$supervisor_pid"; then
      supervisor_gone=false
    fi
    if [[ "$supervisor_gone" == true ]] && ! is_healthy && [[ -z "$(managed_browser_pids)" ]]; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

signal_supervisor_if_managed() {
  local pid="$1"
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  if supervisor_identity_matches "$pid"; then
    jobtomatik_signal_if_identity TERM "$pid" "$SCRIPT_PATH" "supervise" || true
    return 0
  fi
  echo "ANDROID_BROWSER_STALE_SUPERVISOR_PID_REJECTED pid=$pid action=not_signaled" >&2
}

supervisor_signal_handler() {
  touch "$STOP_FILE"
  stop_browser_processes TERM || true
}

case "$ACTION" in
  status)
    if is_healthy; then
      echo "ANDROID_BROWSER_CDP_CONNECTED"
      curl -fsS "$(cdp_url)"
      exit 0
    fi
    echo "ANDROID_BROWSER_CDP_DISCONNECTED"
    exit 1
    ;;

  stop)
    touch "$STOP_FILE"
    supervisor_pid=""
    if [[ -f "$SUPERVISOR_PID_FILE" ]]; then
      supervisor_pid="$(cat "$SUPERVISOR_PID_FILE" 2>/dev/null || true)"
    fi

    # Stop the owned Chromium first. The supervisor can be blocked in `wait`, so
    # signalling only the shell is insufficient. Identity is bound to the exact
    # JobTomatik profile and CDP port, not to a brittle executable basename.
    stop_browser_processes TERM
    if [[ -n "$supervisor_pid" ]]; then
      signal_supervisor_if_managed "$supervisor_pid"
    fi

    if ! wait_for_shutdown "$supervisor_pid"; then
      echo "ANDROID_BROWSER_CDP_STOP_ESCALATING signal=KILL" >&2
      stop_browser_processes KILL
      if [[ -n "$supervisor_pid" ]]; then
        signal_supervisor_if_managed "$supervisor_pid"
      fi
      if ! wait_for_shutdown "$supervisor_pid"; then
        echo "ANDROID_BROWSER_CDP_STOP_TIMEOUT" >&2
        exit 1
      fi
    fi

    rm -f "$SUPERVISOR_PID_FILE" "$BROWSER_PID_FILE"
    if command -v termux-wake-unlock >/dev/null 2>&1; then
      termux-wake-unlock >/dev/null 2>&1 || true
    fi
    echo "ANDROID_BROWSER_CDP_STOPPED"
    ;;

  restart|recover)
    "$SCRIPT_PATH" stop
    rm -f "$STOP_FILE"
    exec "$SCRIPT_PATH" start "$START_URL"
    ;;

  foreground)
    rm -f "$STOP_FILE"
    browser_command
    ;;

  supervise)
    trap supervisor_signal_handler TERM INT HUP
    echo "$$" > "$SUPERVISOR_PID_FILE"
    while [[ ! -f "$STOP_FILE" ]]; do
      rotate_log "$BROWSER_LOG"
      echo "[$(date -Iseconds)] starting Chromium on CDP port $CDP_PORT" >> "$SUPERVISOR_LOG"
      set +e
      browser_command >> "$BROWSER_LOG" 2>&1 &
      browser_pid=$!
      echo "$browser_pid" > "$BROWSER_PID_FILE"
      wait "$browser_pid"
      exit_code=$?
      set -e
      rm -f "$BROWSER_PID_FILE"
      if [[ -f "$STOP_FILE" ]]; then
        break
      fi
      echo "[$(date -Iseconds)] Chromium exited with code $exit_code; restarting in 3 seconds" >> "$SUPERVISOR_LOG"
      sleep 3
    done
    rm -f "$SUPERVISOR_PID_FILE" "$BROWSER_PID_FILE"
    ;;

  start)
    if is_healthy; then
      echo "ANDROID_BROWSER_CDP_CONNECTED"
      exit 0
    fi

    if command -v termux-wake-lock >/dev/null 2>&1; then
      termux-wake-lock >/dev/null 2>&1 || true
    fi

    rm -f "$STOP_FILE"
    if [[ -f "$SUPERVISOR_PID_FILE" ]]; then
      old_pid="$(cat "$SUPERVISOR_PID_FILE" 2>/dev/null || true)"
      if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
        if supervisor_identity_matches "$old_pid"; then
          if wait_for_health 40; then
            echo "ANDROID_BROWSER_CDP_CONNECTED"
            exit 0
          fi
          signal_supervisor_if_managed "$old_pid"
        else
          echo "ANDROID_BROWSER_STALE_SUPERVISOR_PID_REJECTED pid=$old_pid action=not_signaled" >&2
        fi
      fi
      rm -f "$SUPERVISOR_PID_FILE"
    fi

    rotate_log "$SUPERVISOR_LOG"
    rotate_log "$BROWSER_LOG"
    nohup "$SCRIPT_PATH" supervise "$START_URL" \
      >> "$SUPERVISOR_LOG" 2>&1 </dev/null &
    supervisor_pid=$!
    echo "$supervisor_pid" > "$SUPERVISOR_PID_FILE"

    if wait_for_health 80; then
      echo "ANDROID_BROWSER_CDP_CONNECTED"
      echo "Supervisor PID: $supervisor_pid"
      echo "CDP endpoint: http://127.0.0.1:$CDP_PORT"
      exit 0
    fi

    echo "Android Chromium did not expose CDP within 40 seconds." >&2
    tail -n 40 "$SUPERVISOR_LOG" >&2 || true
    tail -n 40 "$BROWSER_LOG" >&2 || true
    exit 1
    ;;
esac

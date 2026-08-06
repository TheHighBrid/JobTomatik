#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

PROFILE_DIR="${JOBTOMATIK_ANDROID_BROWSER_PROFILE:-$HOME/.jobtomatik-chromium}"
CDP_PORT="${JOBTOMATIK_ANDROID_BROWSER_PORT:-9222}"
DISPLAY_VALUE="${DISPLAY:-:0}"
BROWSER_BIN="${JOBTOMATIK_ANDROID_BROWSER_BIN:-$(command -v chromium-browser || true)}"
RUNTIME_DIR="${JOBTOMATIK_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"
SUPERVISOR_PID_FILE="$RUNTIME_DIR/chromium-supervisor.pid"
STOP_FILE="$RUNTIME_DIR/chromium-supervisor.stop"
SUPERVISOR_LOG="$RUNTIME_DIR/chromium-supervisor.log"
BROWSER_LOG="$RUNTIME_DIR/chromium.log"
DEFAULT_URL="https://www.linkedin.com/feed/"
SCRIPT_PATH="$(cd -- "$(dirname -- "$0")" && pwd)/$(basename -- "$0")"

ACTION="${1:-start}"
case "$ACTION" in
  start|stop|restart|status|foreground|supervise)
    shift || true
    ;;
  http://*|https://*)
    DEFAULT_URL="$ACTION"
    ACTION="start"
    shift || true
    ;;
  *)
    echo "Usage: $0 [start|stop|restart|status|foreground] [url]" >&2
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

browser_command() {
  "$BROWSER_BIN" \
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

stop_browser_processes() {
  local pid
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    kill -TERM "$pid" 2>/dev/null || true
  done < <(pgrep -f "chromium-browser.*remote-debugging-port=${CDP_PORT}" 2>/dev/null || true)
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
    if [[ -f "$SUPERVISOR_PID_FILE" ]]; then
      supervisor_pid="$(cat "$SUPERVISOR_PID_FILE" 2>/dev/null || true)"
      if [[ -n "$supervisor_pid" ]]; then
        kill -TERM "$supervisor_pid" 2>/dev/null || true
      fi
    fi
    stop_browser_processes
    rm -f "$SUPERVISOR_PID_FILE"
    if command -v termux-wake-unlock >/dev/null 2>&1; then
      termux-wake-unlock >/dev/null 2>&1 || true
    fi
    echo "ANDROID_BROWSER_CDP_STOPPED"
    ;;

  restart)
    "$SCRIPT_PATH" stop || true
    rm -f "$STOP_FILE"
    exec "$SCRIPT_PATH" start "$START_URL"
    ;;

  foreground)
    rm -f "$STOP_FILE"
    browser_command
    ;;

  supervise)
    trap 'touch "$STOP_FILE"' TERM INT HUP
    echo "$$" > "$SUPERVISOR_PID_FILE"
    while [[ ! -f "$STOP_FILE" ]]; do
      echo "[$(date -Iseconds)] starting Chromium on CDP port $CDP_PORT" >> "$SUPERVISOR_LOG"
      set +e
      browser_command >> "$BROWSER_LOG" 2>&1
      exit_code=$?
      set -e
      if [[ -f "$STOP_FILE" ]]; then
        break
      fi
      echo "[$(date -Iseconds)] Chromium exited with code $exit_code; restarting in 3 seconds" >> "$SUPERVISOR_LOG"
      sleep 3
    done
    rm -f "$SUPERVISOR_PID_FILE"
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
        if wait_for_health 40; then
          echo "ANDROID_BROWSER_CDP_CONNECTED"
          exit 0
        fi
        kill -TERM "$old_pid" 2>/dev/null || true
      fi
      rm -f "$SUPERVISOR_PID_FILE"
    fi

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

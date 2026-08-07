#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ACTION="${1:-start}"
PROOT_DISTRO="${JOBTOMATIK_PROOT_DISTRO:-ubuntu}"
PROOT_REPO="${JOBTOMATIK_PROOT_REPO:-/root/JobTomatik}"
BROWSER_COMMAND="${JOBTOMATIK_BROWSER_COMMAND:-jobtomatik-browser}"
RUNTIME_DIR="${JOBTOMATIK_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"
STACK_PID_FILE="$RUNTIME_DIR/proot-stack.pid"
STACK_LOG="$RUNTIME_DIR/proot-stack.log"

mkdir -p "$RUNTIME_DIR"

run_stack_foreground() {
  local action="$1"
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && bash backend/scripts/manage_android_stack.sh '$action'"
}

supervisor_alive() {
  [[ -f "$STACK_PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$STACK_PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

start_stack_detached() {
  local action="$1"
  if [[ "$action" == "start" ]] && supervisor_alive; then
    if run_stack_foreground status; then
      echo "JOBTOMATIK_PROOT_SUPERVISOR_ALREADY_READY"
      return 0
    fi
  fi

  : > "$STACK_LOG"
  nohup proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && bash backend/scripts/manage_android_stack.sh '$action' && exec sleep infinity" \
    > "$STACK_LOG" 2>&1 </dev/null &

  local proot_pid=$!
  echo "$proot_pid" > "$STACK_PID_FILE"

  for _ in {1..360}; do
    if grep -q 'JOBTOMATIK_ANDROID_STACK_READY' "$STACK_LOG" 2>/dev/null; then
      tail -n 30 "$STACK_LOG"
      echo "PROOT stack PID: $proot_pid"
      return 0
    fi
    if ! kill -0 "$proot_pid" 2>/dev/null; then
      echo "The PRoot stack process exited before JobTomatik became ready." >&2
      tail -n 140 "$STACK_LOG" >&2 || true
      return 1
    fi
    sleep 1
  done

  echo "The PRoot stack did not become ready within 360 seconds." >&2
  tail -n 140 "$STACK_LOG" >&2 || true
  return 1
}

stop_stack_supervisor() {
  run_stack_foreground stop || true
  if supervisor_alive; then
    local stack_pid
    stack_pid="$(cat "$STACK_PID_FILE")"
    kill -TERM "$stack_pid" 2>/dev/null || true
  fi
  rm -f "$STACK_PID_FILE"
}

install_native_commands() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && bash backend/scripts/install_android_native_browser_launcher.sh"
}

update_main() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO'; git fetch origin main; git switch main; git pull --ff-only origin main"
}

case "$ACTION" in
  start)
    "$BROWSER_COMMAND" start
    start_stack_detached start
    ;;
  restart)
    stop_stack_supervisor
    # Keep a healthy authenticated browser and its active handoff page intact.
    "$BROWSER_COMMAND" start
    start_stack_detached restart
    ;;
  status)
    "$BROWSER_COMMAND" status || true
    run_stack_foreground status
    ;;
  stop)
    stop_stack_supervisor
    "$BROWSER_COMMAND" stop
    ;;
  update)
    update_main
    install_native_commands
    stop_stack_supervisor
    "$BROWSER_COMMAND" start
    start_stack_detached restart
    ;;
  *)
    echo "Usage: jobtomatik [start|restart|status|stop|update]" >&2
    exit 2
    ;;
esac
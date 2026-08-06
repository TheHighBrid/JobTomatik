#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ACTION="${1:-start}"
PROOT_DISTRO="${JOBTOMATIK_PROOT_DISTRO:-ubuntu}"
PROOT_REPO="${JOBTOMATIK_PROOT_REPO:-/root/JobTomatik}"
PROOT_ROOTFS="${JOBTOMATIK_PROOT_ROOTFS:-$PREFIX/var/lib/proot-distro/installed-rootfs/$PROOT_DISTRO}"
HOST_REPO="$PROOT_ROOTFS$PROOT_REPO"
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

start_stack_detached() {
  local action="$1"
  : > "$STACK_LOG"

  nohup proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && exec bash backend/scripts/manage_android_stack.sh '$action'" \
    > "$STACK_LOG" 2>&1 </dev/null &

  local proot_pid=$!
  echo "$proot_pid" > "$STACK_PID_FILE"

  for _ in {1..180}; do
    if grep -q 'JOBTOMATIK_ANDROID_STACK_READY' "$STACK_LOG" 2>/dev/null; then
      tail -n 20 "$STACK_LOG"
      echo "PROOT stack PID: $proot_pid"
      return 0
    fi
    if ! kill -0 "$proot_pid" 2>/dev/null; then
      echo "The PRoot stack process exited before JobTomatik became ready." >&2
      tail -n 100 "$STACK_LOG" >&2 || true
      return 1
    fi
    sleep 1
  done

  echo "The PRoot stack did not become ready within 180 seconds." >&2
  tail -n 100 "$STACK_LOG" >&2 || true
  return 1
}

stop_stack_supervisor() {
  run_stack_foreground stop || true
  if [[ -f "$STACK_PID_FILE" ]]; then
    local stack_pid
    stack_pid="$(cat "$STACK_PID_FILE" 2>/dev/null || true)"
    if [[ -n "$stack_pid" ]] && kill -0 "$stack_pid" 2>/dev/null; then
      kill -TERM "$stack_pid" 2>/dev/null || true
    fi
    rm -f "$STACK_PID_FILE"
  fi
}

install_native_commands() {
  local installer="$HOST_REPO/backend/scripts/install_android_native_browser_launcher.sh"
  if [[ ! -f "$installer" ]]; then
    echo "Native launcher installer is missing at $installer" >&2
    exit 1
  fi
  bash "$installer"
}

case "$ACTION" in
  start)
    "$BROWSER_COMMAND" start
    start_stack_detached start
    ;;
  restart)
    stop_stack_supervisor
    "$BROWSER_COMMAND" restart
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
    proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
      "cd '$PROOT_REPO' && git pull --ff-only"
    install_native_commands
    stop_stack_supervisor
    "$BROWSER_COMMAND" restart
    start_stack_detached restart
    ;;
  *)
    echo "Usage: jobtomatik [start|restart|status|stop|update]" >&2
    exit 2
    ;;
esac

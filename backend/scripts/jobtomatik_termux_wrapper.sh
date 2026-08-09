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
    "cd '$PROOT_REPO' && export JOBTOMATIK_RUNTIME_MODE=android_managed && bash backend/scripts/manage_android_stack.sh '$action'"
}

run_frontend_guard() {
  local action="$1"
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && bash backend/scripts/android_frontend_guard.sh '$action'"
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
    if run_stack_foreground status && run_frontend_guard status; then
      echo "JOBTOMATIK_PROOT_SUPERVISOR_ALREADY_READY"
      return 0
    fi
  fi

  # When a new PRoot supervisor is about to take ownership, remove only a narrowly
  # identified JobTomatik Vite server rooted in this checkout. This prevents an old
  # manual frontend from being mistaken for the managed localhost:3000 runtime.
  run_frontend_guard reset

  : > "$STACK_LOG"
  # Source the manager in the same long-lived shell that becomes the supervisor.
  # Under PRoot, children launched by a short-lived nested bash can disappear after
  # that bash exits even when an outer PRoot session remains alive. Sourcing keeps
  # API, Celery worker, and Beat parented to the supervisor shell before it execs
  # into the long-lived sleep process. The managed runtime mode is exported before
  # the manager runs so Celery Beat selects the Android-safe non-persistent scheduler.
  nohup proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && export JOBTOMATIK_RUNTIME_MODE=android_managed && source backend/scripts/manage_android_stack.sh '$action' && exec sleep infinity" \
    > "$STACK_LOG" 2>&1 </dev/null &

  local proot_pid=$!
  echo "$proot_pid" > "$STACK_PID_FILE"

  for _ in {1..360}; do
    if grep -q 'JOBTOMATIK_ANDROID_STACK_READY' "$STACK_LOG" 2>/dev/null; then
      tail -n 30 "$STACK_LOG"
      if ! run_frontend_guard status; then
        echo "The Android stack reported ready without a manager-owned frontend." >&2
        return 1
      fi
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

activate_stack() {
  local action="$1"
  "$BROWSER_COMMAND" start
  # The PRoot manager owns API, worker, frontend, stale-attempt recovery, queue-canary
  # certification, and the single deliberate localhost:3000 JobTomatik-tab reload.
  start_stack_detached "$action"
}

case "$ACTION" in
  start)
    activate_stack start
    ;;
  restart)
    stop_stack_supervisor
    # Preserve the authenticated native browser. The authoritative PRoot manager
    # refreshes only localhost:3000 JobTomatik tabs after the new runtime is ready.
    activate_stack restart
    ;;
  status)
    "$BROWSER_COMMAND" status || true
    run_stack_foreground status
    run_frontend_guard status
    ;;
  stop)
    stop_stack_supervisor
    "$BROWSER_COMMAND" stop
    ;;
  update)
    update_main
    install_native_commands
    stop_stack_supervisor
    activate_stack restart
    ;;
  *)
    echo "Usage: jobtomatik [start|restart|status|stop|update]" >&2
    exit 2
    ;;
esac

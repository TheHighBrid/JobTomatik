#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ACTION="${1:-start}"
PROOT_DISTRO="${JOBTOMATIK_PROOT_DISTRO:-ubuntu}"
PROOT_REPO="${JOBTOMATIK_PROOT_REPO:-/root/JobTomatik}"
BROWSER_COMMAND="${JOBTOMATIK_BROWSER_COMMAND:-jobtomatik-browser}"
RUNTIME_DIR="${JOBTOMATIK_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"
STACK_PID_FILE="$RUNTIME_DIR/proot-stack.pid"
STACK_LOG="$RUNTIME_DIR/proot-stack.log"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PROCESS_IDENTITY_HELPER="${JOBTOMATIK_PROCESS_IDENTITY_HELPER:-$SCRIPT_DIR/jobtomatik_process_identity.sh}"

if [[ ! -r "$PROCESS_IDENTITY_HELPER" ]]; then
  echo "JobTomatik Android process-identity helper is missing: $PROCESS_IDENTITY_HELPER" >&2
  exit 1
fi
# shellcheck source=jobtomatik_process_identity.sh
source "$PROCESS_IDENTITY_HELPER"

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

sanitize_runtime_pid_files() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && bash backend/scripts/sanitize_android_runtime_pid_files.sh"
}

ensure_frontend_native_dependencies() {
  # Never dlopen Android native addons from this foreground, terminal-attached path.
  # The repair step verifies the exact lockfile package/version/binary and SRI for any
  # downloaded replacement. The first native execution happens only after the stack
  # manager is detached, when Vite starts under managed ownership and logs failures.
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO'; backend/.venv/bin/python backend/scripts/repair_android_frontend_native_deps.py; echo 'ANDROID_FRONTEND_NATIVE_REPAIR_READY'"
}

supervisor_identity_matches() {
  local pid="$1"
  jobtomatik_pid_has_all_tokens "$pid" "proot" "manage_android_stack.sh"
}

supervisor_alive() {
  [[ -f "$STACK_PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$STACK_PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  supervisor_identity_matches "$pid"
}

reject_stack_supervisor() {
  local proot_pid="$1"
  if kill -0 "$proot_pid" 2>/dev/null; then
    if supervisor_identity_matches "$proot_pid"; then
      jobtomatik_signal_if_identity TERM "$proot_pid" "proot" "manage_android_stack.sh" || true
    else
      echo "JOBTOMATIK_STALE_PROOT_PID_REJECTED pid=$proot_pid action=not_signaled" >&2
    fi
  fi
  rm -f "$STACK_PID_FILE"
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
  # that bash exits even when an outer PRoot session remains alive. The manager
  # currently resolves its own location from $0, so launch an inner Bash with argv0
  # set to the manager path before sourcing it. This preserves source semantics while
  # making BACKEND_ROOT/REPO_ROOT resolution identical to direct script execution.
  nohup proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && export JOBTOMATIK_RUNTIME_MODE=android_managed && exec bash -c 'source \"\$0\" \"\$1\" && exec sleep infinity' backend/scripts/manage_android_stack.sh '$action'" \
    > "$STACK_LOG" 2>&1 </dev/null &

  local proot_pid=$!
  echo "$proot_pid" > "$STACK_PID_FILE"

  for _ in {1..360}; do
    if grep -q 'JOBTOMATIK_ANDROID_STACK_READY' "$STACK_LOG" 2>/dev/null; then
      if ! run_frontend_guard status; then
        echo "JOBTOMATIK_ANDROID_STACK_READY_REJECTED_FRONTEND_UNATTESTED" >&2
        reject_stack_supervisor "$proot_pid"
        grep -v '^JOBTOMATIK_ANDROID_STACK_READY$' "$STACK_LOG" | tail -n 140 >&2 || true
        return 1
      fi
      tail -n 30 "$STACK_LOG"
      echo "PROOT stack PID: $proot_pid"
      return 0
    fi
    if ! kill -0 "$proot_pid" 2>/dev/null; then
      rm -f "$STACK_PID_FILE"
      echo "The PRoot stack process exited before JobTomatik became ready." >&2
      tail -n 140 "$STACK_LOG" >&2 || true
      return 1
    fi
    sleep 1
  done

  echo "The PRoot stack did not become ready within 360 seconds." >&2
  reject_stack_supervisor "$proot_pid"
  tail -n 140 "$STACK_LOG" >&2 || true
  return 1
}

stop_stack_supervisor() {
  # PID files survive crashes, while Android can recycle their numeric PIDs. Remove
  # any PID file that no longer points at the exact JobTomatik process before the
  # legacy manager stop path is allowed to signal anything.
  sanitize_runtime_pid_files || return 1
  run_stack_foreground stop || true
  if [[ -f "$STACK_PID_FILE" ]]; then
    local stack_pid
    stack_pid="$(cat "$STACK_PID_FILE" 2>/dev/null || true)"
    if [[ -n "$stack_pid" ]] && kill -0 "$stack_pid" 2>/dev/null; then
      if supervisor_identity_matches "$stack_pid"; then
        jobtomatik_signal_if_identity TERM "$stack_pid" "proot" "manage_android_stack.sh" || true
      else
        echo "JOBTOMATIK_STALE_PROOT_PID_REJECTED pid=$stack_pid action=not_signaled" >&2
      fi
    fi
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
  sanitize_runtime_pid_files
  # Repair the complete platform-native frontend toolchain declared by the exact
  # lockfile. Android native addon execution is deliberately deferred until the
  # detached manager launches Vite, so a native crash cannot take down the terminal.
  ensure_frontend_native_dependencies
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

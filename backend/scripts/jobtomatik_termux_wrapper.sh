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
FRONTEND_RUNTIME_MODE="static_artifact"

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
    "cd '$PROOT_REPO' && export JOBTOMATIK_RUNTIME_MODE=android_managed JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE' && bash backend/scripts/manage_android_stack.sh '$action'"
}

run_frontend_guard() {
  local action="$1"
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && export JOBTOMATIK_RUNTIME_MODE=android_managed JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE' && bash backend/scripts/android_frontend_guard.sh '$action'"
}

sanitize_runtime_pid_files() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && export JOBTOMATIK_RUNTIME_MODE=android_managed JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE' && bash backend/scripts/sanitize_android_runtime_pid_files.sh"
}

ensure_static_frontend_artifact() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO'; export JOBTOMATIK_RUNTIME_MODE=android_managed JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE'; backend/.venv/bin/python backend/scripts/install_android_static_frontend_artifact.py"
}

run_runtime_acceptance() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO'; export JOBTOMATIK_RUNTIME_MODE=android_managed JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE'; backend/.venv/bin/python backend/scripts/android_runtime_acceptance.py"
}

run_browser_playwright_probe() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO/backend'; export JOBTOMATIK_RUNTIME_MODE=android_managed; .venv/bin/python - <<'PY'
import asyncio

from app.services.browser_runtime import probe_external_playwright_cdp


async def main() -> None:
    proof = await probe_external_playwright_cdp('http://127.0.0.1:9222')
    if proof.get('playwright_attach_ready') is not True:
        raise SystemExit(1)
    if proof.get('browser_owned_by_jobtomatik') is not False:
        raise SystemExit(1)
    print('ANDROID_BROWSER_PLAYWRIGHT_CDP_READY')


asyncio.run(main())
PY"
}

ensure_browser_playwright_ready() {
  local initial_probe
  if initial_probe="$(run_browser_playwright_probe 2>&1)"; then
    [[ -n "$initial_probe" ]] && printf '%s\n' "$initial_probe"
    return 0
  fi

  echo "ANDROID_BROWSER_PLAYWRIGHT_CDP_STALE action=recover_once"
  "$BROWSER_COMMAND" recover

  local recovery_probe
  if recovery_probe="$(run_browser_playwright_probe 2>&1)"; then
    [[ -n "$recovery_probe" ]] && printf '%s\n' "$recovery_probe"
    echo "ANDROID_BROWSER_PLAYWRIGHT_CDP_RECOVERED"
    return 0
  fi

  echo "ANDROID_BROWSER_PLAYWRIGHT_CDP_RECOVERY_FAILED" >&2
  [[ -n "$recovery_probe" ]] && printf '%s\n' "$recovery_probe" >&2
  return 1
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

  run_frontend_guard reset

  : > "$STACK_LOG"
  nohup proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && export JOBTOMATIK_RUNTIME_MODE=android_managed JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE' && exec bash -c 'source \"\$0\" \"\$1\" && exec sleep infinity' backend/scripts/manage_android_stack.sh '$action'" \
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
  ensure_static_frontend_artifact

  # `jobtomatik start` is idempotent. Never recycle the external authenticated
  # Chromium while the managed stack is already live and healthy because that could
  # interrupt an in-flight application session. The authoritative acceptance check
  # remains safe and non-destructive for this already-running path.
  if [[ "$action" == "start" ]] && supervisor_alive; then
    if run_stack_foreground status && run_frontend_guard status; then
      echo "JOBTOMATIK_PROOT_SUPERVISOR_ALREADY_READY"
      run_runtime_acceptance
      return 0
    fi
  fi

  "$BROWSER_COMMAND" start
  # HTTP CDP alone is insufficient. Prove the exact Playwright attach path used by
  # the managed worker. If it is stale, the native launcher performs one bounded,
  # blocking recovery that waits for the old endpoint to disappear before restart.
  ensure_browser_playwright_ready
  start_stack_detached "$action"
  run_runtime_acceptance
}

case "$ACTION" in
  start)
    activate_stack start
    ;;
  restart)
    stop_stack_supervisor
    # The authenticated native browser is preserved unless the real Playwright
    # probe proves its CDP session stale. Recovery keeps the same persistent profile.
    activate_stack restart
    ;;
  status)
    "$BROWSER_COMMAND" status || true
    run_stack_foreground status
    run_frontend_guard status
    ;;
  acceptance)
    "$BROWSER_COMMAND" status
    run_stack_foreground status
    run_frontend_guard status
    run_runtime_acceptance
    ;;
  qualify)
    echo "JOBTOMATIK_DIRECT_QUALIFICATION_RETIRED"
    echo "Qualification is account-scoped and runs automatically from the authenticated Shadow Campaign Center 4-hour start."
    exit 2
    ;;
  stop)
    stop_stack_supervisor
    "$BROWSER_COMMAND" stop
    ;;
  update)
    update_main
    install_native_commands
    echo "JOBTOMATIK_ANDROID_LAUNCHER_REEXECUTING"
    exec "${JOBTOMATIK_STACK_COMMAND:-$0}" restart
    ;;
  *)
    echo "Usage: jobtomatik [start|restart|status|acceptance|qualify|stop|update]" >&2
    exit 2
    ;;
esac

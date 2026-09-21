#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ACTION="${1:-start}"
PROOT_DISTRO="${JOBTOMATIK_PROOT_DISTRO:-ubuntu}"
PROOT_REPO="${JOBTOMATIK_PROOT_REPO:-/root/JobTomatik}"
BROWSER_COMMAND="${JOBTOMATIK_BROWSER_COMMAND:-jobtomatik-browser}"
PILOT_CONTROLLER_MANAGER="${JOBTOMATIK_PILOT_CONTROLLER_MANAGER:-jobtomatik-pilot-controller-manager}"
RUNTIME_DIR="${JOBTOMATIK_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"
STACK_PID_FILE="$RUNTIME_DIR/proot-stack.pid"
STACK_LOG="$RUNTIME_DIR/proot-stack.log"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PROCESS_IDENTITY_HELPER="${JOBTOMATIK_PROCESS_IDENTITY_HELPER:-$SCRIPT_DIR/jobtomatik_process_identity.sh}"
DEPLOYMENT_RESTART_MARKER="${JOBTOMATIK_DEPLOYMENT_RESTART_MARKER:-$SCRIPT_DIR/.jobtomatik-deployment-restart.pending}"
FRONTEND_RUNTIME_MODE="static_artifact"

if [[ ! -r "$PROCESS_IDENTITY_HELPER" ]]; then
  echo "JobTomatik Android process-identity helper is missing: $PROCESS_IDENTITY_HELPER" >&2
  exit 1
fi
# shellcheck source=jobtomatik_process_identity.sh
source "$PROCESS_IDENTITY_HELPER"

mkdir -p "$RUNTIME_DIR"

ensure_pilot_controller() {
  "$PILOT_CONTROLLER_MANAGER" start
}

pilot_controller_status() {
  "$PILOT_CONTROLLER_MANAGER" status
}

stop_pilot_controller() {
  "$PILOT_CONTROLLER_MANAGER" stop || true
}

run_stack_foreground() {
  local action="$1"
  local migration_flag=0
  if [[ "${JOBTOMATIK_MIGRATE_LEGACY_BROWSER_ENDPOINT:-0}" == "1" ]]; then
    migration_flag=1
  fi
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && export JOBTOMATIK_RUNTIME_MODE=android_managed JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE' JOBTOMATIK_MIGRATE_LEGACY_BROWSER_ENDPOINT='$migration_flag' && bash backend/scripts/manage_android_stack.sh '$action'"
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
  # The certification runtime no longer executes Node, Vite, Lightning CSS, Rolldown,
  # Tailwind Oxide, or any other frontend native addon on the Android device. GitHub
  # Actions builds immutable static bytes for the exact revision. The installer accepts
  # only an artifact whose workflow head SHA, package-lock hash, archive digest, and
  # internal dist-tree hash all match this checkout.
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO'; export JOBTOMATIK_RUNTIME_MODE=android_managed JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE'; backend/.venv/bin/python backend/scripts/install_android_static_frontend_artifact.py"
}

run_runtime_acceptance() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO'; export JOBTOMATIK_RUNTIME_MODE=android_managed JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE'; backend/.venv/bin/python backend/scripts/android_runtime_acceptance.py"
}

run_browser_playwright_probe() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO/backend'; unset APPLICATION_BROWSER_CDP_ENDPOINT APPLICATION_BROWSER_PROVIDER; export JOBTOMATIK_RUNTIME_MODE=android_managed; .venv/bin/python - <<'PY'
import asyncio

from app.services.browser_runtime import probe_external_playwright_cdp
from app.config import get_settings


async def main() -> None:
    proof = await probe_external_playwright_cdp(get_settings().application_browser_cdp_endpoint)
    if proof.get('playwright_attach_ready') is not True:
        raise SystemExit(1)
    if proof.get('browser_owned_by_jobtomatik') is not False:
        raise SystemExit(1)
    if proof.get('connection_identity_verified') is not True:
        raise SystemExit('ANDROID_NATIVE_CHROME_CONNECTION_UNVERIFIED')
    print('ANDROID_BROWSER_PLAYWRIGHT_CDP_READY')


asyncio.run(main())
PY"
}

run_application_browser_contract() {
  local action="$1"
  local migration_flag=0
  if [[ "${JOBTOMATIK_MIGRATE_LEGACY_BROWSER_ENDPOINT:-0}" == "1" ]]; then
    migration_flag=1
  fi
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO/backend'; export JOBTOMATIK_MIGRATE_LEGACY_BROWSER_ENDPOINT='$migration_flag'; .venv/bin/python -m scripts.application_browser_contract '$action'"
}

native_android_chrome_cdp_ready() {
  run_application_browser_contract identity
}

ensure_application_browser_endpoint() {
  local fields
  fields="$(run_application_browser_contract config)" || return 1
  local -a contract
  mapfile -t contract <<< "$fields"
  if [[ "${contract[0]:-}" != native_chrome || ! "${contract[2]:-}" =~ ^[0-9]+$ ]]; then
    echo "ANDROID_APPLICATION_BROWSER_CONFIG_INVALID" >&2
    return 1
  fi
  # This retired shell-only selection must not contradict the worker contract.
  if [[ "${JOBTOMATIK_ANDROID_APPLICATION_BROWSER_MODE:-native_chrome}" != native_chrome ]]; then
    echo "ANDROID_APPLICATION_BROWSER_MODE_CONFLICT: managed applications require native Chrome" >&2
    return 1
  fi
  if [[ "${JOBTOMATIK_REQUIRE_ISOLATED_BROWSER_PROFILE:-0}" == "1" ]]; then
    echo "ANDROID_NATIVE_CHROME_PROFILE_ISOLATION_UNSUPPORTED: this lane requires a separate browser profile; native Android Chrome cannot satisfy that contract" >&2
    return 1
  fi
  if ! command -v adb >/dev/null 2>&1; then
    echo "ANDROID_NATIVE_CHROME_ADB_UNAVAILABLE" >&2
    return 1
  fi
  local devices
  devices="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
  local -a connected=()
  if [[ -n "$devices" ]]; then mapfile -t connected <<< "$devices"; fi
  local serial="${ANDROID_SERIAL:-}"
  if [[ -z "$serial" && "${#connected[@]}" -eq 1 ]]; then serial="${connected[0]}"; fi
  if [[ -z "$serial" ]]; then
    echo "ANDROID_NATIVE_CHROME_DEVICE_REQUIRED: select one connected authorized ADB device" >&2
    return 1
  fi
  local serial_connected=0
  local connected_serial
  for connected_serial in "${connected[@]}"; do
    if [[ "$connected_serial" == "$serial" ]]; then
      serial_connected=1
      break
    fi
  done
  if [[ "$serial_connected" -ne 1 ]]; then
    echo "ANDROID_NATIVE_CHROME_DEVICE_REQUIRED: selected ANDROID_SERIAL is not an authorized connected device" >&2
    return 1
  fi

  # A ready HTTP endpoint is not enough. Bind the host port to the exact selected
  # ADB transport so a stale forward cannot silently control another device's
  # authenticated Chrome profile.
  local forward_list
  forward_list="$(adb forward --list 2>/dev/null || true)"
  local -a port_bindings=()
  if [[ -n "$forward_list" ]]; then
    mapfile -t port_bindings < <(
      awk -v local_port="tcp:${contract[2]}" '$2 == local_port { print $1 "|" $2 "|" $3 }' <<< "$forward_list"
    )
  fi
  if [[ "${#port_bindings[@]}" -gt 1 ]]; then
    echo "ANDROID_NATIVE_CHROME_FORWARD_AMBIGUOUS: multiple ADB forwards claim tcp:${contract[2]}" >&2
    return 1
  fi

  if [[ "${#port_bindings[@]}" -eq 1 ]]; then
    local owner remote_socket
    IFS='|' read -r owner _ remote_socket <<< "${port_bindings[0]}"
    if [[ "$owner" != "$serial" || "$remote_socket" != "localabstract:chrome_devtools_remote" ]]; then
      echo "ANDROID_NATIVE_CHROME_FORWARD_DEVICE_MISMATCH: tcp:${contract[2]} is not bound to the selected device Chrome socket" >&2
      return 1
    fi
    if native_android_chrome_cdp_ready; then
      return 0
    fi
  else
    if native_android_chrome_cdp_ready; then
      echo "ANDROID_NATIVE_CHROME_FORWARD_UNVERIFIED: ready CDP endpoint has no matching ADB forward for the selected device" >&2
      return 1
    fi
    # Do not replace an existing listener or take over another browser's port.
    if ! adb -s "$serial" forward --no-rebind "tcp:${contract[2]}" localabstract:chrome_devtools_remote; then
      echo "ANDROID_NATIVE_CHROME_FORWARD_FAILED: preserve retained applications; inspect the selected device and port" >&2
      return 1
    fi
  fi
  for _ in {1..4}; do
    if native_android_chrome_cdp_ready; then return 0; fi
    sleep 0.25
  done
  echo "ANDROID_NATIVE_CHROME_CDP_REQUIRED: application browser paused; no Chromium fallback" >&2
  return 1
}

ensure_browser_playwright_ready() {
  local initial_probe
  if initial_probe="$(run_browser_playwright_probe 2>&1)"; then
    [[ -n "$initial_probe" ]] && printf '%s\n' "$initial_probe"
    return 0
  fi

  # Deployment markers never grant authority to substitute browser providers.
  # Preserve native Chrome even if it disconnects between the identity and attach
  # checks. The worker independently enforces the same identity before every job.
  echo "ANDROID_BROWSER_PLAYWRIGHT_CDP_STALE action=preserve_browser_fail" >&2
  [[ -n "$initial_probe" ]] && printf '%s\n' "$initial_probe" >&2
  return 1
}

consume_deployment_restart_marker() {
  # A completed native-launcher install authorizes one narrow configuration migration:
  # the old managed 9222 default may move to 9223 before native Chrome is validated.
  # This never authorizes provider substitution, browser recycling, or migration of
  # any other explicit endpoint.
  if [[ -f "$DEPLOYMENT_RESTART_MARKER" ]]; then
    export JOBTOMATIK_MIGRATE_LEGACY_BROWSER_ENDPOINT=1
  fi
  rm -f "$DEPLOYMENT_RESTART_MARKER"
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

  # Retire only a narrowly identified JobTomatik static frontend or legacy Vite
  # process. The guard refuses to signal an unrelated process occupying port 3000.
  run_frontend_guard reset

  : > "$STACK_LOG"
  # Source the manager in the same long-lived shell that becomes the supervisor.
  # This preserves the Android worker/Beat parenting fix while the frontend itself is
  # now a plain Python static server over a SHA-bound CI artifact.
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

verify_backend_environment() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO'; backend/.venv/bin/python backend/scripts/verify_python_environment_requirements.py --requirements backend/requirements.txt"
}

sync_backend_environment() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO'; backend/.venv/bin/python -m pip install --disable-pip-version-check -r backend/requirements.txt; backend/.venv/bin/python backend/scripts/verify_python_environment_requirements.py --requirements backend/requirements.txt"
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
  ensure_application_browser_endpoint
  # Persist exactly the configuration the launcher just validated, before probing
  # through the same settings loader used by the sanitized worker.
  run_stack_foreground configure-browser
  # HTTP CDP alone is insufficient. Prove the worker's actual connection identity.
  # Every start/restart preserves Chrome and fails closed on a disconnect.
  ensure_browser_playwright_ready
  # The PRoot manager owns API, worker, Beat and the attested static frontend. Native
  # Chrome remains outside PRoot and is crossed only through the localhost CDP
  # protocol boundary.
  start_stack_detached "$action"
  run_runtime_acceptance
  ensure_pilot_controller
}

case "$ACTION" in
  browser-preflight)
    verify_backend_environment
    ensure_application_browser_endpoint
    # Persist the validated default/explicit endpoint before the probe reloads
    # backend settings inside PRoot.
    run_stack_foreground configure-browser
    ensure_browser_playwright_ready
    ;;
  start)
    verify_backend_environment
    # `jobtomatik start` is idempotent. Never recycle the external authenticated
    # Chromium while the managed stack is already live and healthy because that could
    # interrupt an in-flight application session.
    if supervisor_alive && run_stack_foreground status && run_frontend_guard status; then
      ensure_application_browser_endpoint
      run_stack_foreground configure-browser
      ensure_browser_playwright_ready
      echo "JOBTOMATIK_PROOT_SUPERVISOR_ALREADY_READY"
      run_runtime_acceptance
      ensure_pilot_controller
    else
      consume_deployment_restart_marker
      activate_stack start
    fi
    ;;
  restart)
    verify_backend_environment
    stop_stack_supervisor
    # Deployment markers are consumed for compatibility, never to replace Chrome.
    consume_deployment_restart_marker
    activate_stack restart
    ;;
  status)
    verify_backend_environment
    native_android_chrome_cdp_ready
    run_stack_foreground status
    run_frontend_guard status
    pilot_controller_status || true
    ;;
  acceptance)
    verify_backend_environment
    # Acceptance evidence is device-bound, not merely browser-package-bound. Recheck
    # the exact selected ADB serial and forward before a PASS receipt can be written.
    ensure_application_browser_endpoint
    run_stack_foreground status
    run_frontend_guard status
    run_runtime_acceptance
    pilot_controller_status || true
    ;;
  qualify)
    # Direct database qualification is intentionally retired. It cannot establish the
    # authenticated campaign owner and previously guessed from active-user cardinality.
    # The real Android 4h start now runs qualification automatically for get_current_user.
    echo "JOBTOMATIK_DIRECT_QUALIFICATION_RETIRED"
    echo "Qualification is account-scoped and runs automatically from the authenticated Shadow Campaign Center 4-hour start."
    exit 2
    ;;
  stop)
    stop_pilot_controller
    stop_stack_supervisor
    echo "ANDROID_NATIVE_CHROME_PRESERVED_ON_STOP"
    ;;
  update)
    update_main
    sync_backend_environment
    install_native_commands
    # Never call activate_stack restart from this pre-update shell: Bash parsed this
    # launcher before the git pull, so its functions can belong to the previous
    # revision even though install_native_commands has already replaced the file on
    # disk. Re-exec the freshly installed launcher so restart uses the pulled code.
    # The old deployment marker is consumed by restart without browser recycling.
    echo "JOBTOMATIK_ANDROID_LAUNCHER_REEXECUTING"
    exec "${JOBTOMATIK_STACK_COMMAND:-$0}" restart
    ;;
  *)
    echo "Usage: jobtomatik [browser-preflight|start|restart|status|acceptance|qualify|stop|update]" >&2
    exit 2
    ;;
esac

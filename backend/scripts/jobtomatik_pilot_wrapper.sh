#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ACTION="${1:-status}"
PROOT_DISTRO="${JOBTOMATIK_PROOT_DISTRO:-ubuntu}"
PROOT_REPO="${JOBTOMATIK_PROOT_REPO:-/root/JobTomatik}"
STACK_COMMAND="${JOBTOMATIK_STACK_COMMAND:-jobtomatik}"
RUNTIME_DIR="${JOBTOMATIK_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"
PENDING_MARKER="$RUNTIME_DIR/lever-pilot-runtime.pending"
ACTIVE_MARKER="$RUNTIME_DIR/lever-pilot-runtime.active"
ARM_TRANSITION_ACTIVE=0

mkdir -p "$RUNTIME_DIR"

run_pilot_mode() {
  local action="$1"
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO/backend'; .venv/bin/python scripts/lever_supervised_pilot_runtime.py '$action'"
}

generate_launch_token() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO/backend'; .venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))'"
}

create_runtime_marker() {
  local launch_token="$1"
  local owner_pid="$$"
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO/backend'; .venv/bin/python scripts/lever_supervised_pilot_runtime.py create-marker --owner-pid '$owner_pid' --launch-token '$launch_token'"
}

verify_runtime_marker() {
  local launch_token="$1"
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO/backend'; .venv/bin/python scripts/lever_supervised_pilot_runtime.py verify-marker --launch-token '$launch_token'"
}

run_stack_sanitized() {
  local action="$1"
  local launch_token="${2:-}"
  (
    # Process environment is authoritative for both Pydantic and operations policy.
    # Never let caller-shell values or an alternate operations env file widen this
    # narrow supervised window. Only this invocation receives the random capability
    # token; the managed stack forwards it across env -i solely to API/worker/Beat.
    unset JOBTOMATIK_OPERATIONS_ENV_FILE
    unset JOBTOMATIK_SUPERVISED_LEVER_PILOT_RUNTIME
    unset JOBTOMATIK_LEVER_PILOT_LAUNCH_TOKEN
    export AUTOPILOT_ENABLED=false
    export ALLOW_REAL_APPLICATION_SUBMIT=false
    export ALLOW_REAL_FOLLOWUP_SEND=false
    export GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
    export LEVER_SUPERVISED_PILOT_ENABLED=false
    if [[ -n "$launch_token" ]]; then
      export JOBTOMATIK_LEVER_PILOT_LAUNCH_TOKEN="$launch_token"
    fi
    "$STACK_COMMAND" "$action"
  )
}

write_pending_marker() {
  local temporary="${PENDING_MARKER}.tmp.$$"
  printf '%s\n' "lever_supervised_ephemeral" > "$temporary"
  chmod 600 "$temporary"
  mv -f "$temporary" "$PENDING_MARKER"
  sync "$PENDING_MARKER" 2>/dev/null || sync
}

clear_transition_markers() {
  rm -f "$PENDING_MARKER" "$ACTIVE_MARKER"
}

clear_runtime_marker_or_contain() {
  if run_pilot_mode clear-marker; then
    return 0
  fi
  echo "Unable to clear the ephemeral Lever runtime marker. Stopping the managed stack instead of risking a supervised restart." >&2
  "$STACK_COMMAND" stop || true
  return 1
}

rollback_to_safe_mode() {
  trap - EXIT INT TERM HUP
  echo "JOBTOMATIK_LEVER_PILOT_ROLLBACK_BEGIN" >&2

  if ! clear_runtime_marker_or_contain; then
    return 1
  fi

  if ! run_pilot_mode persist-safe; then
    echo "Unable to persist the fail-safe switches. Stopping the managed stack instead of restarting it." >&2
    "$STACK_COMMAND" stop || true
    return 1
  fi

  if ! run_stack_sanitized restart; then
    echo "Fail-safe switches are persisted OFF, but the managed safe restart failed." >&2
    return 1
  fi

  clear_transition_markers
  echo "JOBTOMATIK_LEVER_PILOT_ROLLBACK_SAFE" >&2
}

arm_exit() {
  local exit_code="${1:-1}"
  trap - EXIT INT TERM HUP
  if [[ "$ARM_TRANSITION_ACTIVE" == "1" ]]; then
    rollback_to_safe_mode || true
  fi
  exit "$exit_code"
}

arm_pilot() {
  local launch_token

  # Durable configuration always remains fail-safe. The temporary capability comes
  # from one random token plus the owner/revision-bound marker for this exact restart.
  run_pilot_mode persist-safe
  run_pilot_mode preflight-arm
  launch_token="$(generate_launch_token)"
  if [[ ${#launch_token} -lt 32 ]]; then
    echo "Unable to generate the supervised Lever restart capability token." >&2
    return 1
  fi

  rm -f "$ACTIVE_MARKER"
  write_pending_marker
  ARM_TRANSITION_ACTIVE=1
  trap 'arm_exit $?' EXIT INT TERM HUP

  create_runtime_marker "$launch_token"
  verify_runtime_marker "$launch_token"

  if ! run_stack_sanitized restart "$launch_token"; then
    echo "Lever supervised runtime failed validation; restoring the ordinary safe runtime." >&2
    rollback_to_safe_mode
    ARM_TRANSITION_ACTIVE=0
    trap - EXIT INT TERM HUP
    return 1
  fi

  # The native owner is still alive, so owner/token/revision binding must survive the
  # full managed restart. The wrapper never persists or prints the raw launch token.
  if ! verify_runtime_marker "$launch_token"; then
    echo "The exact Lever restart marker expired during restart; restoring the safe runtime." >&2
    rollback_to_safe_mode
    ARM_TRANSITION_ACTIVE=0
    trap - EXIT INT TERM HUP
    return 1
  fi

  mv -f "$PENDING_MARKER" "$ACTIVE_MARKER"
  sync "$ACTIVE_MARKER" 2>/dev/null || sync
  ARM_TRANSITION_ACTIVE=0
  trap - EXIT INT TERM HUP

  echo "JOBTOMATIK_LEVER_PILOT_ARMED_EPHEMERAL"
  echo "Persisted submit flags remain OFF. One-time exact application approval is still required in JobTomatik."
}

disarm_pilot() {
  if ! clear_runtime_marker_or_contain; then
    return 1
  fi

  if ! run_pilot_mode persist-safe; then
    echo "Unable to persist the fail-safe switches. Stopping the managed stack to contain the live window." >&2
    "$STACK_COMMAND" stop || true
    return 1
  fi

  # With the capability marker removed, persisted flags OFF, and a sanitized launch
  # environment, the new processes can only start in the ordinary fail-safe mode.
  if ! run_stack_sanitized restart; then
    echo "The supervised runtime was stopped, but the ordinary safe stack did not restart cleanly." >&2
    return 1
  fi

  clear_transition_markers
  echo "JOBTOMATIK_LEVER_PILOT_DISARMED"
}

status_pilot() {
  run_pilot_mode status
  if [[ -f "$PENDING_MARKER" ]]; then
    echo "JOBTOMATIK_LEVER_PILOT_TRANSITION: INCOMPLETE_PENDING_SAFE_RECOVERY"
  elif [[ -f "$ACTIVE_MARKER" ]]; then
    echo "JOBTOMATIK_LEVER_PILOT_TRANSITION: LAST_VERIFIED_LAUNCH_WAS_SUPERVISED_LEVER"
  else
    echo "JOBTOMATIK_LEVER_PILOT_TRANSITION: NO_ACTIVE_MARKER"
  fi
  "$STACK_COMMAND" status
}

case "$ACTION" in
  arm)
    arm_pilot
    ;;
  disarm)
    disarm_pilot
    ;;
  status)
    status_pilot
    ;;
  *)
    echo "Usage: jobtomatik-pilot [arm|disarm|status]" >&2
    exit 2
    ;;
esac

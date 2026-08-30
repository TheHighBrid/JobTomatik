#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ACTION="${1:-status}"
PROOT_DISTRO="${JOBTOMATIK_PROOT_DISTRO:-ubuntu}"
PROOT_REPO="${JOBTOMATIK_PROOT_REPO:-/root/JobTomatik}"
STACK_COMMAND="${JOBTOMATIK_STACK_COMMAND:-jobtomatik}"

run_pilot_mode() {
  local action="$1"
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "set -e; cd '$PROOT_REPO/backend'; .venv/bin/python scripts/lever_supervised_pilot_runtime.py '$action'"
}

rollback_to_safe_mode() {
  echo "JOBTOMATIK_LEVER_PILOT_ROLLBACK_BEGIN" >&2
  run_pilot_mode disarm || true
  # The persisted flags are already OFF before this restart attempt. Even if the
  # runtime itself has another fault, a later successful restart cannot inherit an
  # armed Lever pilot from this failed transition.
  "$STACK_COMMAND" restart || true
  echo "JOBTOMATIK_LEVER_PILOT_ROLLBACK_PERSISTED_SAFE" >&2
}

arm_pilot() {
  # This changes only runtime feature switches. It does not create the per-application
  # one-time approval required by the supervised submission API.
  run_pilot_mode arm

  if ! "$STACK_COMMAND" restart; then
    echo "Lever pilot restart failed; restoring fail-safe runtime switches." >&2
    rollback_to_safe_mode
    return 1
  fi

  if ! run_pilot_mode verify-armed; then
    echo "Lever pilot runtime did not verify after restart; restoring fail-safe switches." >&2
    rollback_to_safe_mode
    return 1
  fi

  echo "JOBTOMATIK_LEVER_PILOT_ARMED"
  echo "One-time exact application approval is still required in JobTomatik before any final submit attempt."
}

disarm_pilot() {
  # Persist safe values first. A restart failure therefore cannot leave the next
  # successful process launch armed by accident.
  run_pilot_mode disarm

  if ! "$STACK_COMMAND" restart; then
    echo "Lever pilot flags are persisted OFF, but the managed stack restart failed." >&2
    echo "Run 'jobtomatik status' to inspect the unrelated runtime failure." >&2
    return 1
  fi

  run_pilot_mode verify-disarmed
  echo "JOBTOMATIK_LEVER_PILOT_DISARMED"
}

case "$ACTION" in
  arm)
    arm_pilot
    ;;
  disarm)
    disarm_pilot
    ;;
  status)
    run_pilot_mode status
    "$STACK_COMMAND" status
    ;;
  *)
    echo "Usage: jobtomatik-pilot [arm|disarm|status]" >&2
    exit 2
    ;;
esac

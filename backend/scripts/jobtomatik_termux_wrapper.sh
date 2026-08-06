#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ACTION="${1:-start}"
PROOT_REPO="${JOBTOMATIK_PROOT_REPO:-/root/JobTomatik}"
BROWSER_COMMAND="${JOBTOMATIK_BROWSER_COMMAND:-jobtomatik-browser}"

run_stack() {
  local action="$1"
  proot-distro login ubuntu --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && bash backend/scripts/manage_android_stack.sh '$action'"
}

case "$ACTION" in
  start|restart)
    "$BROWSER_COMMAND" restart
    run_stack restart
    ;;
  status)
    "$BROWSER_COMMAND" status || true
    run_stack status
    ;;
  stop)
    run_stack stop || true
    "$BROWSER_COMMAND" stop
    ;;
  update)
    proot-distro login ubuntu --shared-tmp -- bash -lc \
      "cd '$PROOT_REPO' && git pull --ff-only"
    "$BROWSER_COMMAND" restart
    run_stack restart
    ;;
  *)
    echo "Usage: jobtomatik [start|restart|status|stop|update]" >&2
    exit 2
    ;;
esac

#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ACTION="${1:-start}"
PROOT_DISTRO="${JOBTOMATIK_PROOT_DISTRO:-ubuntu}"
PROOT_REPO="${JOBTOMATIK_PROOT_REPO:-/root/JobTomatik}"
PROOT_ROOTFS="${JOBTOMATIK_PROOT_ROOTFS:-$PREFIX/var/lib/proot-distro/installed-rootfs/$PROOT_DISTRO}"
HOST_REPO="$PROOT_ROOTFS$PROOT_REPO"
BROWSER_COMMAND="${JOBTOMATIK_BROWSER_COMMAND:-jobtomatik-browser}"

run_stack() {
  local action="$1"
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
    "cd '$PROOT_REPO' && bash backend/scripts/manage_android_stack.sh '$action'"
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
    run_stack start
    ;;
  restart)
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
    proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc \
      "cd '$PROOT_REPO' && git pull --ff-only"
    install_native_commands
    "$BROWSER_COMMAND" restart
    run_stack restart
    ;;
  *)
    echo "Usage: jobtomatik [start|restart|status|stop|update]" >&2
    exit 2
    ;;
esac

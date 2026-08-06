#!/usr/bin/env bash
set -euo pipefail

BACKEND_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
SOURCE="$BACKEND_ROOT/scripts/start_android_browser_cdp.sh"
TERMUX_PREFIX="${JOBTOMATIK_TERMUX_PREFIX:-/data/data/com.termux/files/usr}"
DEST_DIR="$TERMUX_PREFIX/bin"
BROWSER_DEST="$DEST_DIR/jobtomatik-browser"
STACK_DEST="$DEST_DIR/jobtomatik"

if [[ ! -f "$SOURCE" ]]; then
  echo "Android browser launcher source is missing: $SOURCE" >&2
  exit 1
fi

if [[ ! -d "$DEST_DIR" ]]; then
  echo "Native Termux bin directory is not visible at $DEST_DIR" >&2
  echo "Enter Ubuntu with: proot-distro login ubuntu --shared-tmp" >&2
  exit 1
fi

cp "$SOURCE" "$BROWSER_DEST"
chmod 755 "$BROWSER_DEST"

cat > "$STACK_DEST" <<'TERMUX_WRAPPER'
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
TERMUX_WRAPPER
chmod 755 "$STACK_DEST"

echo "ANDROID_BROWSER_LAUNCHER_INSTALLED"
echo "Browser command: $BROWSER_DEST"
echo "Stack command: $STACK_DEST"

#!/usr/bin/env bash
set -euo pipefail

BACKEND_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
BROWSER_SOURCE="$BACKEND_ROOT/scripts/start_android_browser_cdp.sh"
STACK_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_termux_wrapper.sh"
PILOT_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_pilot_wrapper.sh"
IDENTITY_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_process_identity.sh"
TERMUX_PREFIX="${JOBTOMATIK_TERMUX_PREFIX:-/data/data/com.termux/files/usr}"
DEST_DIR="$TERMUX_PREFIX/bin"
BROWSER_DEST="$DEST_DIR/jobtomatik-browser"
STACK_DEST="$DEST_DIR/jobtomatik"
PILOT_DEST="$DEST_DIR/jobtomatik-pilot"
IDENTITY_DEST="$DEST_DIR/jobtomatik_process_identity.sh"
DEPLOYMENT_RESTART_MARKER="${JOBTOMATIK_DEPLOYMENT_RESTART_MARKER:-$DEST_DIR/.jobtomatik-deployment-restart.pending}"

for source_file in "$BROWSER_SOURCE" "$STACK_SOURCE" "$PILOT_SOURCE" "$IDENTITY_SOURCE"; do
  if [[ ! -f "$source_file" ]]; then
    echo "Android launcher source is missing: $source_file" >&2
    exit 1
  fi
done

if [[ ! -d "$DEST_DIR" ]]; then
  echo "Native Termux bin directory is not visible at $DEST_DIR" >&2
  echo "Run this installer through: proot-distro login ubuntu --shared-tmp" >&2
  exit 1
fi

install_atomically() {
  local source_file="$1"
  local destination="$2"
  local temporary="${destination}.tmp.$$"
  cp "$source_file" "$temporary"
  chmod 755 "$temporary"
  mv -f "$temporary" "$destination"
}

install_atomically "$IDENTITY_SOURCE" "$IDENTITY_DEST"
install_atomically "$BROWSER_SOURCE" "$BROWSER_DEST"
install_atomically "$STACK_SOURCE" "$STACK_DEST"
install_atomically "$PILOT_SOURCE" "$PILOT_DEST"

# The current launcher may have been parsed before a git update replaced these files.
# Mark the completed native deployment so the freshly installed wrapper can distinguish
# its one deployment restart from ordinary user/runtime restarts. The new wrapper
# consumes this marker before any optional stale-CDP recovery, making recovery bounded
# to one browser recycle per completed native launcher installation.
touch "$DEPLOYMENT_RESTART_MARKER"

echo "ANDROID_BROWSER_LAUNCHER_INSTALLED"
echo "Native prefix: $TERMUX_PREFIX"
echo "Browser command: $BROWSER_DEST"
echo "Stack command: $STACK_DEST"
echo "Lever pilot command: $PILOT_DEST"
echo "Process identity helper: $IDENTITY_DEST"
echo "Deployment recovery marker: $DEPLOYMENT_RESTART_MARKER"

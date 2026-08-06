#!/usr/bin/env bash
set -euo pipefail

BACKEND_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
BROWSER_SOURCE="$BACKEND_ROOT/scripts/start_android_browser_cdp.sh"
STACK_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_termux_wrapper.sh"
TERMUX_PREFIX="${JOBTOMATIK_TERMUX_PREFIX:-/data/data/com.termux/files/usr}"
DEST_DIR="$TERMUX_PREFIX/bin"
BROWSER_DEST="$DEST_DIR/jobtomatik-browser"
STACK_DEST="$DEST_DIR/jobtomatik"

for source_file in "$BROWSER_SOURCE" "$STACK_SOURCE"; do
  if [[ ! -f "$source_file" ]]; then
    echo "Android launcher source is missing: $source_file" >&2
    exit 1
  fi
done

if [[ ! -d "$DEST_DIR" ]]; then
  echo "Native Termux bin directory is not visible at $DEST_DIR" >&2
  echo "Enter Ubuntu with: proot-distro login ubuntu --shared-tmp" >&2
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

install_atomically "$BROWSER_SOURCE" "$BROWSER_DEST"
install_atomically "$STACK_SOURCE" "$STACK_DEST"

echo "ANDROID_BROWSER_LAUNCHER_INSTALLED"
echo "Browser command: $BROWSER_DEST"
echo "Stack command: $STACK_DEST"

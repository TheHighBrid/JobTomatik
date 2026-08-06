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

cp "$BROWSER_SOURCE" "$BROWSER_DEST"
cp "$STACK_SOURCE" "$STACK_DEST"
chmod 755 "$BROWSER_DEST" "$STACK_DEST"

echo "ANDROID_BROWSER_LAUNCHER_INSTALLED"
echo "Browser command: $BROWSER_DEST"
echo "Stack command: $STACK_DEST"

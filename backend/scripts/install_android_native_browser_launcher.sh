#!/usr/bin/env bash
set -euo pipefail

BACKEND_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
SOURCE="$BACKEND_ROOT/scripts/start_android_browser_cdp.sh"
TERMUX_HOME="${JOBTOMATIK_TERMUX_HOME:-/data/data/com.termux/files/home}"
DEST_DIR="$TERMUX_HOME/.local/bin"
DEST="$DEST_DIR/jobtomatik-browser"

if [[ ! -f "$SOURCE" ]]; then
  echo "Android browser launcher source is missing: $SOURCE" >&2
  exit 1
fi

if [[ ! -d "$TERMUX_HOME" ]]; then
  echo "Native Termux home is not visible at $TERMUX_HOME" >&2
  echo "Enter Ubuntu with: proot-distro login ubuntu --shared-tmp" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
cp "$SOURCE" "$DEST"
chmod 755 "$DEST"

echo "ANDROID_BROWSER_LAUNCHER_INSTALLED"
echo "Launcher: $DEST"

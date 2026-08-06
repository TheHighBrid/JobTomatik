#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

PROFILE_DIR="${JOBTOMATIK_ANDROID_BROWSER_PROFILE:-$HOME/.jobtomatik-chromium}"
CDP_PORT="${JOBTOMATIK_ANDROID_BROWSER_PORT:-9222}"
DISPLAY_VALUE="${DISPLAY:-:0}"
BROWSER_BIN="${JOBTOMATIK_ANDROID_BROWSER_BIN:-$(command -v chromium-browser || true)}"

if [[ -z "$BROWSER_BIN" ]]; then
  echo "chromium-browser was not found in native Termux." >&2
  echo "Install it with: pkg install x11-repo chromium" >&2
  exit 1
fi

mkdir -p "$PROFILE_DIR"
export DISPLAY="$DISPLAY_VALUE"

exec "$BROWSER_BIN" \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --disable-features=Vulkan,WebGPU \
  --ozone-platform=x11 \
  --no-first-run \
  --no-default-browser-check \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="$CDP_PORT" \
  --user-data-dir="$PROFILE_DIR" \
  "${1:-https://www.linkedin.com/feed/}"

#!/usr/bin/env bash
set -euo pipefail

BACKEND_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
BROWSER_SOURCE="$BACKEND_ROOT/scripts/start_android_browser_cdp.sh"
STACK_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_termux_wrapper.sh"
PILOT_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_pilot_wrapper.sh"
PILOT_CONTROLLER_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_pilot_control_daemon.sh"
PILOT_CONTROLLER_MANAGER_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_pilot_controller_manager.sh"
IDENTITY_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_process_identity.sh"
TERMUX_PREFIX="${JOBTOMATIK_TERMUX_PREFIX:-/data/data/com.termux/files/usr}"
TERMUX_HOME="${JOBTOMATIK_TERMUX_HOME:-${TERMUX_PREFIX%/usr}/home}"
DEST_DIR="$TERMUX_PREFIX/bin"
BROWSER_DEST="$DEST_DIR/jobtomatik-browser"
STACK_DEST="$DEST_DIR/jobtomatik"
PILOT_DEST="$DEST_DIR/jobtomatik-pilot"
PILOT_CONTROLLER_DEST="$DEST_DIR/jobtomatik-pilot-controller"
PILOT_CONTROLLER_MANAGER_DEST="$DEST_DIR/jobtomatik-pilot-controller-manager"
IDENTITY_DEST="$DEST_DIR/jobtomatik_process_identity.sh"
DEPLOYMENT_RESTART_MARKER="${JOBTOMATIK_DEPLOYMENT_RESTART_MARKER:-$DEST_DIR/.jobtomatik-deployment-restart.pending}"
ADB_SERIAL_STATE="${JOBTOMATIK_ADB_SERIAL_STATE:-$TERMUX_HOME/.jobtomatik-runtime/android-serial}"

for source_file in "$BROWSER_SOURCE" "$STACK_SOURCE" "$PILOT_SOURCE" "$PILOT_CONTROLLER_SOURCE" "$PILOT_CONTROLLER_MANAGER_SOURCE" "$IDENTITY_SOURCE"; do
  [[ -f "$source_file" ]] || { echo "Android launcher source is missing: $source_file" >&2; exit 1; }
done
[[ -d "$DEST_DIR" ]] || { echo "Native Termux bin directory is not visible at $DEST_DIR" >&2; exit 1; }

install_atomically() { local t="${2}.tmp.$$"; cp "$1" "$t"; chmod 755 "$t"; mv -f "$t" "$2"; }
install_atomically "$IDENTITY_SOURCE" "$IDENTITY_DEST"
install_atomically "$BROWSER_SOURCE" "$BROWSER_DEST"
install_atomically "$STACK_SOURCE" "$STACK_DEST"
install_atomically "$PILOT_SOURCE" "$PILOT_DEST"
install_atomically "$PILOT_CONTROLLER_SOURCE" "$PILOT_CONTROLLER_DEST"
install_atomically "$PILOT_CONTROLLER_MANAGER_SOURCE" "$PILOT_CONTROLLER_MANAGER_DEST"

mkdir -p "$(dirname "$ADB_SERIAL_STATE")"
if [[ -n "${ANDROID_SERIAL:-}" && "$ANDROID_SERIAL" =~ ^[^:[:space:]]+:[0-9]+$ ]]; then
  printf '%s\n' "$ANDROID_SERIAL" > "$ADB_SERIAL_STATE"
  chmod 600 "$ADB_SERIAL_STATE"
fi

python3 - "$STACK_DEST" "$ADB_SERIAL_STATE" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1]); state = sys.argv[2]; text = path.read_text()
needle = '  local serial="${ANDROID_SERIAL:-}"\n'
replacement = '''  local serial="${ANDROID_SERIAL:-}"
  local adb_serial_state="${JOBTOMATIK_ADB_SERIAL_STATE:-''' + state + '''}"
  if [[ -z "$serial" && -r "$adb_serial_state" ]]; then
    serial="$(head -n 1 "$adb_serial_state" 2>/dev/null || true)"
    if [[ "$serial" =~ ^[^:[:space:]]+:[0-9]+$ ]]; then
      export ANDROID_SERIAL="$serial"
      echo "ANDROID_NATIVE_CHROME_DEVICE_RESTORED serial=$serial"
    else
      serial=""
    fi
  fi
'''
if needle not in text: raise SystemExit('ANDROID_LAUNCHER_SERIAL_STATE_PATCH_TARGET_MISSING')
text = text.replace(needle, replacement, 1)
old = '''  if [[ "$serial_connected" -ne 1 ]]; then
    echo "ANDROID_NATIVE_CHROME_DEVICE_REQUIRED: selected ANDROID_SERIAL is not an authorized connected device" >&2
    return 1
  fi
'''
new = '''  if [[ "$serial_connected" -ne 1 && "$serial" =~ ^[^:[:space:]]+:[0-9]+$ ]]; then
    local reconnect_result reconnect_state
    reconnect_result="$(adb connect "$serial" 2>&1 || true)"
    reconnect_state="$(adb -s "$serial" get-state 2>/dev/null || true)"
    if [[ "$reconnect_state" == "device" ]]; then
      serial_connected=1
      export ANDROID_SERIAL="$serial"
      printf '%s\\n' "$serial" > "$adb_serial_state"
      chmod 600 "$adb_serial_state" 2>/dev/null || true
      echo "ANDROID_NATIVE_CHROME_DEVICE_RECONNECTED serial=$serial"
    else
      echo "ANDROID_NATIVE_CHROME_DEVICE_RECONNECT_FAILED serial=$serial result=$reconnect_result" >&2
    fi
  fi
  if [[ "$serial_connected" -ne 1 ]]; then
    devices="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
    connected=(); if [[ -n "$devices" ]]; then mapfile -t connected <<< "$devices"; fi
    if [[ "${#connected[@]}" -eq 1 ]]; then
      serial="${connected[0]}"; export ANDROID_SERIAL="$serial"; serial_connected=1
    fi
  fi
  if [[ "$serial_connected" -ne 1 ]]; then
    echo "ANDROID_NATIVE_CHROME_DEVICE_REQUIRED: selected ANDROID_SERIAL is not an authorized connected device" >&2
    return 1
  fi
  if [[ "$serial" =~ ^[^:[:space:]]+:[0-9]+$ ]]; then
    printf '%s\\n' "$serial" > "$adb_serial_state"
    chmod 600 "$adb_serial_state" 2>/dev/null || true
  fi
'''
if old not in text: raise SystemExit('ANDROID_LAUNCHER_ADB_RECONNECT_PATCH_TARGET_MISSING')
path.write_text(text.replace(old, new, 1))
PY
chmod 755 "$STACK_DEST"
touch "$DEPLOYMENT_RESTART_MARKER"

echo "ANDROID_BROWSER_LAUNCHER_INSTALLED"
echo "Native prefix: $TERMUX_PREFIX"
echo "Native home: $TERMUX_HOME"
echo "Browser command: $BROWSER_DEST"
echo "Stack command: $STACK_DEST"
echo "Lever pilot command: $PILOT_DEST"
echo "Lever pilot controller: $PILOT_CONTROLLER_DEST"
echo "Lever pilot controller manager: $PILOT_CONTROLLER_MANAGER_DEST"
echo "Process identity helper: $IDENTITY_DEST"
echo "Deployment recovery marker: $DEPLOYMENT_RESTART_MARKER"
echo "ADB serial state: $ADB_SERIAL_STATE"

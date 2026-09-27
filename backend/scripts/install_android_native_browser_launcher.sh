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
DEST_DIR="$TERMUX_PREFIX/bin"
BROWSER_DEST="$DEST_DIR/jobtomatik-browser"
STACK_DEST="$DEST_DIR/jobtomatik"
PILOT_DEST="$DEST_DIR/jobtomatik-pilot"
PILOT_CONTROLLER_DEST="$DEST_DIR/jobtomatik-pilot-controller"
PILOT_CONTROLLER_MANAGER_DEST="$DEST_DIR/jobtomatik-pilot-controller-manager"
IDENTITY_DEST="$DEST_DIR/jobtomatik_process_identity.sh"
DEPLOYMENT_RESTART_MARKER="${JOBTOMATIK_DEPLOYMENT_RESTART_MARKER:-$DEST_DIR/.jobtomatik-deployment-restart.pending}"

for source_file in \
  "$BROWSER_SOURCE" \
  "$STACK_SOURCE" \
  "$PILOT_SOURCE" \
  "$PILOT_CONTROLLER_SOURCE" \
  "$PILOT_CONTROLLER_MANAGER_SOURCE" \
  "$IDENTITY_SOURCE"; do
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
install_atomically "$PILOT_CONTROLLER_SOURCE" "$PILOT_CONTROLLER_DEST"
install_atomically "$PILOT_CONTROLLER_MANAGER_SOURCE" "$PILOT_CONTROLLER_MANAGER_DEST"

# The update action re-execs the newly installed native wrapper. Do not depend on an
# interactive-shell ANDROID_SERIAL surviving that deployment boundary. Resolve the
# only authorized transport again, and verify an explicitly selected transport with
# adb get-state before rejecting it. This keeps wrong-device protection while avoiding
# a false negative from a transient/stale `adb devices` snapshot.
python3 - "$STACK_DEST" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = '''  local devices
  devices="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
  local -a connected=()
  if [[ -n "$devices" ]]; then mapfile -t connected <<< "$devices"; fi
  local serial="${ANDROID_SERIAL:-}"
  if [[ -z "$serial" && "${#connected[@]}" -eq 1 ]]; then serial="${connected[0]}"; fi
  if [[ -z "$serial" ]]; then
    echo "ANDROID_NATIVE_CHROME_DEVICE_REQUIRED: select one connected authorized ADB device" >&2
    return 1
  fi
  local serial_connected=0
  local connected_serial
  for connected_serial in "${connected[@]}"; do
    if [[ "$connected_serial" == "$serial" ]]; then
      serial_connected=1
      break
    fi
  done
  if [[ "$serial_connected" -ne 1 ]]; then
    echo "ANDROID_NATIVE_CHROME_DEVICE_REQUIRED: selected ANDROID_SERIAL is not an authorized connected device" >&2
    return 1
  fi
'''
new = '''  local devices
  devices="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
  local -a connected=()
  if [[ -n "$devices" ]]; then mapfile -t connected <<< "$devices"; fi
  local serial="${ANDROID_SERIAL:-}"

  # Re-resolve a single authorized transport after `jobtomatik update` re-execs this
  # launcher. ANDROID_SERIAL belongs to the caller's shell and is not deployment state.
  if [[ -z "$serial" && "${#connected[@]}" -eq 1 ]]; then
    serial="${connected[0]}"
    export ANDROID_SERIAL="$serial"
    echo "ANDROID_NATIVE_CHROME_DEVICE_AUTOSELECTED serial=$serial"
  fi
  if [[ -z "$serial" ]]; then
    echo "ANDROID_NATIVE_CHROME_DEVICE_REQUIRED: select one connected authorized ADB device" >&2
    return 1
  fi

  local serial_connected=0
  local connected_serial
  for connected_serial in "${connected[@]}"; do
    if [[ "$connected_serial" == "$serial" ]]; then
      serial_connected=1
      break
    fi
  done

  # ADB's list can briefly lag a live transport during wireless reconnect/re-exec.
  # Verify the exact selected serial directly before declaring it unauthorized.
  if [[ "$serial_connected" -ne 1 ]]; then
    local direct_state
    direct_state="$(adb -s "$serial" get-state 2>/dev/null || true)"
    if [[ "$direct_state" == "device" ]]; then
      serial_connected=1
      export ANDROID_SERIAL="$serial"
      echo "ANDROID_NATIVE_CHROME_DEVICE_REVALIDATED serial=$serial"
    fi
  fi
  if [[ "$serial_connected" -ne 1 ]]; then
    # If the inherited selection is stale but exactly one authorized device is now
    # present, recover to that unambiguous transport rather than fail the deployment.
    if [[ "${#connected[@]}" -eq 1 ]] && [[ "$(adb -s "${connected[0]}" get-state 2>/dev/null || true)" == "device" ]]; then
      serial="${connected[0]}"
      export ANDROID_SERIAL="$serial"
      echo "ANDROID_NATIVE_CHROME_DEVICE_RECOVERED serial=$serial"
    else
      echo "ANDROID_NATIVE_CHROME_DEVICE_REQUIRED: selected ANDROID_SERIAL is not an authorized connected device" >&2
      return 1
    fi
  fi
'''
if old not in text:
    raise SystemExit("ANDROID_LAUNCHER_ADB_SELECTION_PATCH_TARGET_MISSING")
path.write_text(text.replace(old, new, 1))
PY
chmod 755 "$STACK_DEST"

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
echo "Lever pilot controller: $PILOT_CONTROLLER_DEST"
echo "Lever pilot controller manager: $PILOT_CONTROLLER_MANAGER_DEST"
echo "Process identity helper: $IDENTITY_DEST"
echo "Deployment recovery marker: $DEPLOYMENT_RESTART_MARKER"
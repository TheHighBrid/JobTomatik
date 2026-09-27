#!/data/data/com.termux/files/usr/bin/bash
# Shared fail-closed ADB transport selection for the native Android Chrome runtime.
# The selected wireless endpoint is persisted only after adb proves it is authorized,
# so a later JobTomatik invocation can recover from Android dropping the host transport.

jobtomatik_resolve_adb_serial() {
  local state_dir="${JOBTOMATIK_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"
  local selection_file="${JOBTOMATIK_ADB_SELECTION_FILE:-$state_dir/adb-selected-serial}"
  mkdir -p "$state_dir"

  local devices
  devices="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
  local -a connected=()
  if [[ -n "$devices" ]]; then mapfile -t connected <<< "$devices"; fi

  local serial="${ANDROID_SERIAL:-}"
  if [[ -z "$serial" && "${#connected[@]}" -eq 1 ]]; then
    serial="${connected[0]}"
  fi
  if [[ -z "$serial" && -s "$selection_file" ]]; then
    serial="$(head -n 1 "$selection_file" | tr -d '\r\n')"
    if [[ "$serial" =~ [[:space:]] ]]; then serial=""; fi
  fi
  if [[ -z "$serial" ]]; then
    echo "ANDROID_NATIVE_CHROME_DEVICE_REQUIRED: no previously verified ADB device is recoverable" >&2
    return 1
  fi

  local direct_state
  direct_state="$(adb -s "$serial" get-state 2>/dev/null || true)"
  if [[ "$direct_state" != "device" && "$serial" =~ ^[^:[:space:]]+:[0-9]+$ ]]; then
    local reconnect_result
    reconnect_result="$(adb connect "$serial" 2>&1 || true)"
    direct_state="$(adb -s "$serial" get-state 2>/dev/null || true)"
    if [[ "$direct_state" == "device" ]]; then
      echo "ANDROID_NATIVE_CHROME_DEVICE_RECONNECTED serial=$serial" >&2
    else
      echo "ANDROID_NATIVE_CHROME_DEVICE_RECONNECT_FAILED serial=$serial result=$reconnect_result" >&2
    fi
  fi

  if [[ "$direct_state" != "device" ]]; then
    devices="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
    connected=()
    if [[ -n "$devices" ]]; then mapfile -t connected <<< "$devices"; fi
    if [[ "${#connected[@]}" -eq 1 ]] && [[ "$(adb -s "${connected[0]}" get-state 2>/dev/null || true)" == "device" ]]; then
      serial="${connected[0]}"
      direct_state="device"
      echo "ANDROID_NATIVE_CHROME_DEVICE_RECOVERED serial=$serial" >&2
    fi
  fi

  if [[ "$direct_state" != "device" ]]; then
    echo "ANDROID_NATIVE_CHROME_DEVICE_REQUIRED: selected ADB device is not authorized or recoverable" >&2
    return 1
  fi

  export ANDROID_SERIAL="$serial"
  printf '%s\n' "$serial" > "${selection_file}.tmp.$$"
  chmod 600 "${selection_file}.tmp.$$"
  mv -f "${selection_file}.tmp.$$" "$selection_file"
  printf '%s\n' "$serial"
}

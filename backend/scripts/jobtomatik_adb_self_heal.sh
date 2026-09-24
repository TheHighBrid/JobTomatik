#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

RUNTIME_DIR="${JOBTOMATIK_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"
CACHE_FILE="${JOBTOMATIK_ADB_SERIAL_CACHE:-$RUNTIME_DIR/adb-serial}"
CONNECT_TIMEOUT="${JOBTOMATIK_ADB_CONNECT_TIMEOUT_SECONDS:-3}"
MAX_CANDIDATES="${JOBTOMATIK_ADB_MAX_MDNS_CANDIDATES:-8}"
mkdir -p "$RUNTIME_DIR"

connected_devices() {
  adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }'
}

is_connected() {
  local wanted="$1"
  connected_devices | grep -Fxq -- "$wanted"
}

remember_serial() {
  local serial="$1"
  local tmp="${CACHE_FILE}.tmp.$$"
  printf '%s\n' "$serial" > "$tmp"
  chmod 600 "$tmp" 2>/dev/null || true
  mv -f "$tmp" "$CACHE_FILE"
}

mdns_candidates() {
  adb mdns services 2>/dev/null |
    awk '$0 ~ /_adb-tls-connect\._tcp/ { for (i=1; i<=NF; i++) if ($i ~ /:[0-9]+$/) print $i }' |
    sed 's/^\[//; s/\]$//' |
    awk '!seen[$0]++'
}

try_connect() {
  local endpoint="$1"
  if command -v timeout >/dev/null 2>&1; then
    timeout "$CONNECT_TIMEOUT" adb connect "$endpoint" >/dev/null 2>&1 || return 1
  else
    adb connect "$endpoint" >/dev/null 2>&1 || return 1
  fi
  is_connected "$endpoint"
}

resolve_adb_serial() {
  local explicit="${ANDROID_SERIAL:-}"
  if [[ -n "$explicit" ]] && is_connected "$explicit"; then
    remember_serial "$explicit"
    printf '%s\n' "$explicit"
    return 0
  fi

  local -a live=()
  mapfile -t live < <(connected_devices)
  if [[ "${#live[@]}" -eq 1 ]]; then
    remember_serial "${live[0]}"
    printf '%s\n' "${live[0]}"
    return 0
  fi
  if [[ "${#live[@]}" -gt 1 ]]; then
    echo "ANDROID_ADB_SELF_HEAL_AMBIGUOUS: multiple authorized devices are already connected" >&2
    return 1
  fi

  local cached=""
  if [[ -r "$CACHE_FILE" ]]; then cached="$(head -n 1 "$CACHE_FILE" | tr -d '\r\n')"; fi
  if [[ -n "$cached" ]] && try_connect "$cached"; then
    remember_serial "$cached"
    echo "ANDROID_ADB_SELF_HEAL_RECONNECTED source=cache serial=$cached" >&2
    printf '%s\n' "$cached"
    return 0
  fi

  local -a candidates=()
  mapfile -t candidates < <(mdns_candidates | head -n "$MAX_CANDIDATES")
  local candidate
  for candidate in "${candidates[@]}"; do
    [[ -n "$candidate" ]] || continue
    try_connect "$candidate" || true
  done

  mapfile -t live < <(connected_devices)
  if [[ "${#live[@]}" -ne 1 ]]; then
    if [[ "${#live[@]}" -gt 1 ]]; then
      echo "ANDROID_ADB_SELF_HEAL_AMBIGUOUS: mDNS recovery found multiple authorized devices; refusing to guess" >&2
    else
      echo "ANDROID_ADB_SELF_HEAL_UNAVAILABLE: no paired _adb-tls-connect service could be reconnected" >&2
    fi
    return 1
  fi

  remember_serial "${live[0]}"
  echo "ANDROID_ADB_SELF_HEAL_RECONNECTED source=mdns serial=${live[0]}" >&2
  printf '%s\n' "${live[0]}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  resolve_adb_serial
fi

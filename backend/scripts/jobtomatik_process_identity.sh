#!/usr/bin/env bash
# Shared Android runtime process-identity helpers.
# Callers must verify a live PID belongs to the expected JobTomatik process before
# sending any signal. Android/Linux may recycle PIDs after a crash or stale PID file.

jobtomatik_proc_cmdline() {
  local pid="${1:-}"
  local proc_root="${JOBTOMATIK_PROC_ROOT:-/proc}"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [[ -r "$proc_root/$pid/cmdline" ]] || return 1
  tr '\0' ' ' < "$proc_root/$pid/cmdline" 2>/dev/null
}

jobtomatik_proc_cwd() {
  local pid="${1:-}"
  local proc_root="${JOBTOMATIK_PROC_ROOT:-/proc}"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  readlink "$proc_root/$pid/cwd" 2>/dev/null
}

jobtomatik_pid_has_all_tokens() {
  local pid="${1:-}"
  shift || true
  local cmdline
  cmdline="$(jobtomatik_proc_cmdline "$pid")" || return 1
  local token
  for token in "$@"; do
    [[ -n "$token" ]] || continue
    [[ "$cmdline" == *"$token"* ]] || return 1
  done
}

jobtomatik_pid_cwd_is() {
  local pid="${1:-}"
  local expected="${2:-}"
  [[ -n "$expected" ]] || return 1
  local cwd
  cwd="$(jobtomatik_proc_cwd "$pid")" || return 1
  [[ "$cwd" == "$expected" ]]
}

jobtomatik_static_frontend_pid_matches() {
  local pid="${1:-}"
  local expected_python="${2:-}"
  local expected_server="${3:-}"
  local artifacts_root="${4:-}"
  local proc_root="${JOBTOMATIK_PROC_ROOT:-/proc}"

  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [[ -n "$expected_python" && -x "$expected_python" ]] || return 1
  [[ -n "$expected_server" && -n "$artifacts_root" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1

  JOBTOMATIK_EXPECTED_STATIC_PYTHON="$expected_python" \
  JOBTOMATIK_EXPECTED_STATIC_SERVER="$expected_server" \
  JOBTOMATIK_EXPECTED_STATIC_ARTIFACTS_ROOT="$artifacts_root" \
  JOBTOMATIK_PROC_ROOT="$proc_root" \
    "$expected_python" - "$pid" <<'PY' >/dev/null 2>&1
import os
import re
import sys
from pathlib import Path

pid = sys.argv[1]
proc_root = Path(os.environ["JOBTOMATIK_PROC_ROOT"])
expected_python = os.environ["JOBTOMATIK_EXPECTED_STATIC_PYTHON"]
expected_server = os.environ["JOBTOMATIK_EXPECTED_STATIC_SERVER"]
artifacts_root = Path(os.environ["JOBTOMATIK_EXPECTED_STATIC_ARTIFACTS_ROOT"])

try:
    raw = (proc_root / pid / "cmdline").read_bytes()
except OSError:
    raise SystemExit(1)

try:
    argv = [part.decode("utf-8", errors="strict") for part in raw.split(b"\0") if part]
except UnicodeDecodeError:
    raise SystemExit(1)

if len(argv) < 2 or argv[0] != expected_python or argv[1] != expected_server:
    raise SystemExit(1)


def one_value(flag: str) -> str:
    positions = [index for index, value in enumerate(argv) if value == flag]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise SystemExit(1)
    return argv[positions[0] + 1]


revision = one_value("--revision").lower()
if re.fullmatch(r"[0-9a-f]{7,64}", revision) is None:
    raise SystemExit(1)
if one_value("--host") != "127.0.0.1" or one_value("--port") != "3000":
    raise SystemExit(1)

expected_root = artifacts_root / revision / "dist"
expected_manifest = artifacts_root / revision / "jobtomatik-frontend-manifest.json"
if Path(one_value("--root")) != expected_root:
    raise SystemExit(1)
if Path(one_value("--manifest")) != expected_manifest:
    raise SystemExit(1)
raise SystemExit(0)
PY
}

jobtomatik_signal_if_identity() {
  local signal_name="${1:-TERM}"
  local pid="${2:-}"
  shift 2 || true
  if ! jobtomatik_pid_has_all_tokens "$pid" "$@"; then
    return 3
  fi
  kill -"$signal_name" "$pid" 2>/dev/null
}

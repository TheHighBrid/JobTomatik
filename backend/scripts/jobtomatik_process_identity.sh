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

jobtomatik_signal_if_identity() {
  local signal_name="${1:-TERM}"
  local pid="${2:-}"
  shift 2 || true
  if ! jobtomatik_pid_has_all_tokens "$pid" "$@"; then
    return 3
  fi
  kill -"$signal_name" "$pid" 2>/dev/null
}

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PID_DIR="$ROOT_DIR/.codespaces/run"

stop_process() {
  local name="$1"
  local pid_file="$PID_DIR/$name.pid"

  [[ -f "$pid_file" ]] || return
  local pid
  pid="$(cat "$pid_file")"

  if kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    for _ in {1..10}; do
      kill -0 "$pid" >/dev/null 2>&1 || break
      sleep 0.5
    done
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi

  rm -f "$pid_file"
  printf 'Stopped %s.\n' "$name"
}

cd "$ROOT_DIR"
stop_process frontend
stop_process celery-beat
stop_process celery
stop_process backend

docker compose stop db redis >/dev/null 2>&1 || true
printf 'Stopped PostgreSQL and Redis containers.\n'

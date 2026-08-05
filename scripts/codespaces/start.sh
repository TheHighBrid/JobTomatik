#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.codespaces"
LOG_DIR="$RUNTIME_DIR/logs"
PID_DIR="$RUNTIME_DIR/run"
QUIET=false

if [[ "${1:-}" == "--quiet" ]]; then
  QUIET=true
fi

log() {
  $QUIET || printf '%s\n' "$*"
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

wait_for() {
  local description="$1"
  shift
  local attempts=0
  until "$@" >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if (( attempts >= 60 )); then
      fail "$description did not become ready."
    fi
    sleep 1
  done
}

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(cat "$pid_file")"
  kill -0 "$pid" >/dev/null 2>&1
}

start_process() {
  local name="$1"
  local command="$2"
  local pid_file="$PID_DIR/$name.pid"
  local log_file="$LOG_DIR/$name.log"

  if is_running "$pid_file"; then
    log "$name is already running (PID $(cat "$pid_file"))."
    return
  fi

  rm -f "$pid_file"
  nohup bash -lc "$command" >"$log_file" 2>&1 &
  echo $! >"$pid_file"
  sleep 1

  if ! is_running "$pid_file"; then
    tail -n 80 "$log_file" >&2 || true
    fail "$name failed to start."
  fi

  log "Started $name (PID $(cat "$pid_file"))."
}

mkdir -p "$LOG_DIR" "$PID_DIR"
cd "$ROOT_DIR"

[[ -x .venv/bin/python ]] || fail "Missing .venv. Rebuild the Codespace or run scripts/codespaces/bootstrap.sh."
command -v docker >/dev/null 2>&1 || fail "Docker is unavailable in this Codespace."

log "Starting PostgreSQL and Redis containers..."
wait_for "Docker daemon" docker info
docker compose up -d db redis >/dev/null
wait_for "PostgreSQL" docker compose exec -T db pg_isready -U jobtomatik
wait_for "Redis" docker compose exec -T redis redis-cli ping

log "Applying database migrations..."
(
  cd backend
  ../.venv/bin/python -m alembic upgrade head >/dev/null
)

start_process \
  backend \
  "cd '$ROOT_DIR/backend' && exec '$ROOT_DIR/.venv/bin/python' -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info"

start_process \
  celery \
  "cd '$ROOT_DIR/backend' && exec '$ROOT_DIR/.venv/bin/python' -m celery -A app.celery_app worker --loglevel=info --pool=solo --concurrency=1 -Q applications,celery,scraping,followup"

if [[ "${JOBTOMATIK_START_BEAT:-0}" == "1" ]]; then
  start_process \
    celery-beat \
    "cd '$ROOT_DIR/backend' && exec '$ROOT_DIR/.venv/bin/python' -m celery -A app.celery_app beat --loglevel=info"
fi

start_process \
  frontend \
  "cd '$ROOT_DIR/frontend' && VITE_DEV_PROXY_TARGET=http://127.0.0.1:8000 exec npm run dev -- --host 0.0.0.0 --port 3000"

wait_for "JobTomatik API" curl -fsS http://127.0.0.1:8000/api/system/ready
wait_for "JobTomatik frontend" curl -fsS http://127.0.0.1:3000

log ""
log "JobTomatik is running."
log "Frontend: http://127.0.0.1:3000"
log "API:      http://127.0.0.1:8000"
log "API docs: http://127.0.0.1:8000/docs"
log "Logs:     .codespaces/logs/"

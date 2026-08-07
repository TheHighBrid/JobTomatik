#!/usr/bin/env bash
set -euo pipefail

BACKEND_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
REPO_ROOT="$(cd -- "$BACKEND_ROOT/.." && pwd)"
FRONTEND_ROOT="$REPO_ROOT/frontend"
VENV="$BACKEND_ROOT/.venv"
ENV_FILE="$BACKEND_ROOT/.env"
RUNTIME_DIR="$BACKEND_ROOT/.runtime"
LOG_DIR="$RUNTIME_DIR/logs"
API_PID_FILE="$RUNTIME_DIR/api.pid"
CELERY_PID_FILE="$RUNTIME_DIR/celery.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
API_LOG="$LOG_DIR/api.log"
CELERY_LOG="$LOG_DIR/celery.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
ACTION="${1:-start}"
ANDROID_REDIS_URL="${JOBTOMATIK_ANDROID_REDIS_URL:-redis://localhost:6379/1}"

mkdir -p "$RUNTIME_DIR" "$LOG_DIR"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Backend virtual environment is missing at $VENV" >&2
  exit 1
fi

set_env_value() {
  local key="$1"
  local value="$2"
  touch "$ENV_FILE"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '\n%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

ensure_env_default() {
  local key="$1"
  local value="$2"
  touch "$ENV_FILE"
  if ! grep -q "^${key}=" "$ENV_FILE"; then
    printf '\n%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

repair_database_configuration() {
  "$VENV/bin/python" scripts/repair_android_database_url.py \
    --env-file "$ENV_FILE" \
    --runtime-dir "$RUNTIME_DIR"

  local selected_database_url
  selected_database_url="$(
    "$VENV/bin/python" -c \
      'from pathlib import Path; from scripts.repair_android_database_url import read_env_value; import sys; print(read_env_value(Path(sys.argv[1]), "DATABASE_URL") or "")' \
      "$ENV_FILE"
  )"

  if [[ -z "$selected_database_url" ]]; then
    echo "DATABASE_URL could not be resolved after Android runtime repair." >&2
    exit 1
  fi

  export DATABASE_URL="$selected_database_url"
}

pid_file_alive() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

stop_pid_file() {
  local pid_file="$1"
  if ! pid_file_alive "$pid_file"; then
    rm -f "$pid_file"
    return 0
  fi
  local pid
  pid="$(cat "$pid_file")"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in {1..30}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

stop_stack() {
  stop_pid_file "$FRONTEND_PID_FILE"
  stop_pid_file "$CELERY_PID_FILE"
  stop_pid_file "$API_PID_FILE"
  echo "JOBTOMATIK_ANDROID_STACK_STOPPED"
}

http_ready() {
  local url="$1"
  curl -fsS --max-time 2 "$url" >/dev/null 2>&1
}

wait_http() {
  local url="$1"
  local attempts="${2:-100}"
  for ((index = 0; index < attempts; index += 1)); do
    if http_ready "$url"; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

managed_worker_ready() {
  pid_file_alive "$CELERY_PID_FILE" || return 1
  [[ -f "$CELERY_LOG" ]] || return 1
  grep -Eq '(celery@)?jobtomatik-android@.* ready\.' "$CELERY_LOG" \
    && grep -q 'applications' "$CELERY_LOG" \
    && grep -q 'scraping' "$CELERY_LOG"
}

wait_worker() {
  for _ in {1..120}; do
    if managed_worker_ready; then
      return 0
    fi
    if [[ -f "$CELERY_PID_FILE" ]] && ! pid_file_alive "$CELERY_PID_FILE"; then
      return 1
    fi
    sleep 1
  done
  return 1
}

start_api() {
  if http_ready 'http://127.0.0.1:8010/api/system/ready'; then
    echo "API: ADOPTED_EXISTING_READY_PROCESS"
    return 0
  fi
  stop_pid_file "$API_PID_FILE"
  : > "$API_LOG"
  nohup "$VENV/bin/uvicorn" app.main:app \
    --host 127.0.0.1 \
    --port 8010 \
    >"$API_LOG" 2>&1 </dev/null &
  echo $! > "$API_PID_FILE"

  if ! wait_http 'http://127.0.0.1:8010/api/system/ready' 120; then
    echo "API failed to become ready." >&2
    tail -n 100 "$API_LOG" >&2 || true
    return 1
  fi
  echo "API: STARTED"
}

start_worker() {
  if managed_worker_ready; then
    echo "CELERY: EXISTING_MANAGED_WORKER_READY"
    return 0
  fi
  stop_pid_file "$CELERY_PID_FILE"
  : > "$CELERY_LOG"
  nohup "$VENV/bin/celery" -A app.celery_app worker \
    --hostname='jobtomatik-android@%h' \
    --loglevel=info \
    --pool=solo \
    --concurrency=1 \
    --without-gossip \
    --without-mingle \
    -Q applications,celery,followup,scraping \
    >"$CELERY_LOG" 2>&1 </dev/null &
  echo $! > "$CELERY_PID_FILE"

  if ! wait_worker; then
    echo "Celery failed to become ready with the required queues." >&2
    tail -n 140 "$CELERY_LOG" >&2 || true
    return 1
  fi
  echo "CELERY: STARTED_WITH_REQUIRED_QUEUES"
}

start_frontend() {
  if http_ready 'http://127.0.0.1:3000'; then
    echo "FRONTEND: ADOPTED_EXISTING_READY_PROCESS"
    return 0
  fi
  stop_pid_file "$FRONTEND_PID_FILE"
  : > "$FRONTEND_LOG"
  cd "$FRONTEND_ROOT"
  nohup env \
    VITE_API_URL=http://127.0.0.1:8010 \
    VITE_DEV_PROXY_TARGET=http://127.0.0.1:8010 \
    npm run dev -- --host 0.0.0.0 --port 3000 \
    >"$FRONTEND_LOG" 2>&1 </dev/null &
  echo $! > "$FRONTEND_PID_FILE"

  if ! wait_http 'http://127.0.0.1:3000' 120; then
    echo "Frontend failed to become ready." >&2
    tail -n 100 "$FRONTEND_LOG" >&2 || true
    return 1
  fi
  echo "FRONTEND: STARTED"
}

status_stack() {
  local failed=0
  if http_ready 'http://127.0.0.1:8010/api/system/ready'; then
    echo "API: READY"
  else
    echo "API: DOWN"
    failed=1
  fi

  if http_ready 'http://127.0.0.1:3000'; then
    echo "FRONTEND: READY"
  else
    echo "FRONTEND: DOWN"
    failed=1
  fi

  if managed_worker_ready; then
    echo "CELERY: READY applications,celery,followup,scraping"
  else
    echo "CELERY: DOWN_OR_WRONG_QUEUES"
    failed=1
  fi

  if curl -fsS --max-time 2 'http://127.0.0.1:9222/json/version' 2>/dev/null | grep -q webSocketDebuggerUrl; then
    echo "ANDROID_BROWSER_CDP: READY"
  else
    echo "ANDROID_BROWSER_CDP: DOWN"
    failed=1
  fi

  local configured_redis
  configured_redis="$(grep '^REDIS_URL=' "$ENV_FILE" 2>/dev/null | tail -n 1 | cut -d= -f2- || true)"
  if [[ "$configured_redis" == "$ANDROID_REDIS_URL" ]]; then
    echo "ANDROID_RUNTIME_BROKER: ISOLATED"
  else
    echo "ANDROID_RUNTIME_BROKER: NOT_ISOLATED"
    failed=1
  fi
  return "$failed"
}

prepare_stack() {
  cd "$BACKEND_ROOT"

  # Android owns one authoritative API/worker runtime. Use Redis DB 1 so legacy
  # manually launched workers that were already connected to DB 0 cannot consume a
  # newly queued application task with stale imported code. This changes no process
  # outside the managed runtime and therefore never terminates an operator terminal.
  set_env_value REDIS_URL "$ANDROID_REDIS_URL"
  set_env_value APPLICATION_BROWSER_CDP_ENDPOINT 'http://127.0.0.1:9222'
  set_env_value APPLICATION_BROWSER_HEADLESS 'false'
  set_env_value APPLICATION_TARGET_HUMAN_WAIT_SECONDS '0'
  repair_database_configuration

  export REDIS_URL="$ANDROID_REDIS_URL"
  export APPLICATION_BROWSER_CDP_ENDPOINT='http://127.0.0.1:9222'
  export APPLICATION_BROWSER_HEADLESS='false'
  export APPLICATION_TARGET_HUMAN_WAIT_SECONDS='0'

  if ! "$VENV/bin/python" -c 'import jwt; assert jwt.__version__' >/dev/null 2>&1; then
    "$VENV/bin/python" -m pip install --no-cache-dir 'PyJWT==2.13.0'
  fi

  if ! redis-cli ping 2>/dev/null | grep -q PONG; then
    redis-server --daemonize yes
    sleep 1
  fi

  "$VENV/bin/python" scripts/prepare_android_runtime.py | tee "$LOG_DIR/preflight.log"
}

start_stack() {
  prepare_stack
  cd "$BACKEND_ROOT"
  start_api
  start_worker
  start_frontend

  cd "$BACKEND_ROOT"
  echo "JOBTOMATIK_ANDROID_STACK_READY"
  status_stack
  echo "Logs: $LOG_DIR"
}

restart_stack() {
  stop_stack
  start_stack
}

case "$ACTION" in
  start)
    start_stack
    ;;
  restart)
    restart_stack
    ;;
  stop)
    stop_stack
    ;;
  status)
    status_stack
    ;;
  *)
    echo "Usage: $0 [start|restart|stop|status]" >&2
    exit 2
    ;;
esac

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
ACTION="${1:-start}"

mkdir -p "$RUNTIME_DIR" "$LOG_DIR"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Backend virtual environment is missing at $VENV" >&2
  exit 1
fi

ensure_env_default() {
  local key="$1"
  local value="$2"
  touch "$ENV_FILE"
  if ! grep -q "^${key}=" "$ENV_FILE"; then
    printf '\n%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

stop_pid_file() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" 2>/dev/null || true
    for _ in {1..20}; do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.25
    done
    kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

stop_stack() {
  stop_pid_file "$FRONTEND_PID_FILE"
  stop_pid_file "$CELERY_PID_FILE"
  stop_pid_file "$API_PID_FILE"

  pkill -TERM -f 'celery.*worker' 2>/dev/null || true
  pkill -TERM -f 'uvicorn.*app.main:app' 2>/dev/null || true
  pkill -TERM -f 'vite.*--host' 2>/dev/null || true
  sleep 2
  echo "JOBTOMATIK_ANDROID_STACK_STOPPED"
}

http_ready() {
  local url="$1"
  curl -fsS --max-time 2 "$url" >/dev/null 2>&1
}

wait_http() {
  local url="$1"
  local attempts="${2:-80}"
  for ((index = 0; index < attempts; index += 1)); do
    if http_ready "$url"; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

wait_worker() {
  for _ in {1..60}; do
    if "$VENV/bin/celery" -A app.celery_app inspect ping --timeout=1 2>/dev/null | grep -q pong; then
      return 0
    fi
    sleep 1
  done
  return 1
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

  cd "$BACKEND_ROOT"
  if "$VENV/bin/celery" -A app.celery_app inspect ping --timeout=1 2>/dev/null | grep -q pong; then
    echo "CELERY: READY"
  else
    echo "CELERY: DOWN"
    failed=1
  fi

  if curl -fsS --max-time 2 'http://127.0.0.1:9222/json/version' 2>/dev/null | grep -q webSocketDebuggerUrl; then
    echo "ANDROID_BROWSER_CDP: READY"
  else
    echo "ANDROID_BROWSER_CDP: DOWN"
  fi
  return "$failed"
}

start_stack() {
  stop_stack >/dev/null

  cd "$BACKEND_ROOT"

  ensure_env_default DATABASE_URL 'sqlite:///./jobtomatik.db'
  ensure_env_default APPLICATION_BROWSER_CDP_ENDPOINT 'http://127.0.0.1:9222'
  ensure_env_default APPLICATION_BROWSER_HEADLESS 'false'
  ensure_env_default APPLICATION_TARGET_HUMAN_WAIT_SECONDS '600'

  if ! "$VENV/bin/python" -c 'import jwt; assert jwt.__version__' >/dev/null 2>&1; then
    "$VENV/bin/python" -m pip install --no-cache-dir 'PyJWT==2.13.0'
  fi

  if ! redis-cli ping 2>/dev/null | grep -q PONG; then
    redis-server --daemonize yes
    sleep 1
  fi

  "$VENV/bin/python" scripts/prepare_android_runtime.py | tee "$LOG_DIR/preflight.log"

  nohup "$VENV/bin/uvicorn" app.main:app \
    --host 127.0.0.1 \
    --port 8010 \
    >"$LOG_DIR/api.log" 2>&1 </dev/null &
  echo $! > "$API_PID_FILE"

  if ! wait_http 'http://127.0.0.1:8010/api/system/ready' 100; then
    echo "API failed to become ready." >&2
    tail -n 80 "$LOG_DIR/api.log" >&2 || true
    exit 1
  fi

  nohup "$VENV/bin/celery" -A app.celery_app worker \
    --loglevel=info \
    --pool=solo \
    -Q applications,celery,followup,scraping \
    >"$LOG_DIR/celery.log" 2>&1 </dev/null &
  echo $! > "$CELERY_PID_FILE"

  if ! wait_worker; then
    echo "Celery failed to become ready." >&2
    tail -n 100 "$LOG_DIR/celery.log" >&2 || true
    exit 1
  fi

  cd "$FRONTEND_ROOT"
  nohup env \
    VITE_API_URL=http://127.0.0.1:8010 \
    VITE_DEV_PROXY_TARGET=http://127.0.0.1:8010 \
    npm run dev -- --host 0.0.0.0 \
    >"$LOG_DIR/frontend.log" 2>&1 </dev/null &
  echo $! > "$FRONTEND_PID_FILE"

  if ! wait_http 'http://127.0.0.1:3000' 100; then
    echo "Frontend failed to become ready." >&2
    tail -n 80 "$LOG_DIR/frontend.log" >&2 || true
    exit 1
  fi

  cd "$BACKEND_ROOT"
  echo "JOBTOMATIK_ANDROID_STACK_READY"
  status_stack || true
  echo "Logs: $LOG_DIR"
}

case "$ACTION" in
  start)
    start_stack
    ;;
  restart)
    start_stack
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

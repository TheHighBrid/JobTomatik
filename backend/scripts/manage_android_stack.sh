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
LEGACY_ANDROID_REDIS_URL="${JOBTOMATIK_LEGACY_ANDROID_REDIS_URL:-redis://localhost:6379/0}"
RUNTIME_REVISION="${JOBTOMATIK_RUNTIME_REVISION:-$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)}"
RUNTIME_REVISION="${RUNTIME_REVISION:-unknown}"
RUNTIME_REVISION_SHORT="${RUNTIME_REVISION:0:12}"
WORKER_NODE_PREFIX="jobtomatik-android-${RUNTIME_REVISION_SHORT}@"

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

pid_file_value() {
  local pid_file="$1"
  cat "$pid_file" 2>/dev/null || true
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

configured_redis_url() {
  grep '^REDIS_URL=' "$ENV_FILE" 2>/dev/null | tail -n 1 | cut -d= -f2- || true
}

worker_log_ready() {
  pid_file_alive "$CELERY_PID_FILE" || return 1
  [[ -f "$CELERY_LOG" ]] || return 1
  grep -Eq 'jobtomatik-android-[[:alnum:]]+@.* ready\.' "$CELERY_LOG" \
    && grep -q 'applications' "$CELERY_LOG" \
    && grep -q 'scraping' "$CELERY_LOG"
}

worker_control_ready() {
  pid_file_alive "$CELERY_PID_FILE" || return 1
  local broker
  broker="$(configured_redis_url)"
  [[ "$broker" == "$ANDROID_REDIS_URL" ]] || return 1

  (
    cd "$BACKEND_ROOT"
    REDIS_URL="$broker" \
    JOBTOMATIK_EXPECTED_WORKER_PREFIX="$WORKER_NODE_PREFIX" \
    "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import os

from app.celery_app import celery_app

required = {"applications", "celery", "followup", "scraping"}
expected_prefix = os.environ["JOBTOMATIK_EXPECTED_WORKER_PREFIX"]
inspect = celery_app.control.inspect(timeout=2.0)
pings = inspect.ping() or {}
queues = inspect.active_queues() or {}

for node, payload in pings.items():
    if not str(node).startswith(expected_prefix):
        continue
    if not isinstance(payload, dict) or payload.get("ok") != "pong":
        continue
    names = {
        str(item.get("name") or "")
        for item in (queues.get(node) or [])
        if isinstance(item, dict)
    }
    if required.issubset(names):
        raise SystemExit(0)
raise SystemExit(1)
PY
  )
}

worker_application_canary_ready() {
  pid_file_alive "$CELERY_PID_FILE" || return 1
  local broker
  broker="$(configured_redis_url)"
  [[ "$broker" == "$ANDROID_REDIS_URL" ]] || return 1

  (
    cd "$BACKEND_ROOT"
    REDIS_URL="$broker" \
    JOBTOMATIK_RUNTIME_REVISION="$RUNTIME_REVISION" \
    JOBTOMATIK_EXPECTED_REDIS_DB="1" \
    "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import os

from app.tasks.runtime import application_queue_canary

expected_revision = os.environ["JOBTOMATIK_RUNTIME_REVISION"]
expected_db = int(os.environ.get("JOBTOMATIK_EXPECTED_REDIS_DB", "1"))
result = application_queue_canary.apply_async(
    kwargs={"expected_revision": expected_revision},
    queue="applications",
)
try:
    payload = result.get(timeout=12, propagate=True)
finally:
    try:
        result.forget()
    except Exception:
        pass

if not isinstance(payload, dict) or payload.get("ok") is not True:
    raise SystemExit(1)
if payload.get("revision") != expected_revision:
    raise SystemExit(1)
if payload.get("redis_db") != expected_db:
    raise SystemExit(1)
raise SystemExit(0)
PY
  )
}

managed_worker_ready() {
  worker_log_ready && worker_control_ready && worker_application_canary_ready
}

wait_worker() {
  for _ in {1..120}; do
    if worker_log_ready && worker_control_ready; then
      if worker_application_canary_ready; then
        return 0
      fi
    fi
    if [[ -f "$CELERY_PID_FILE" ]] && ! pid_file_alive "$CELERY_PID_FILE"; then
      return 1
    fi
    sleep 1
  done
  return 1
}

start_api() {
  if pid_file_alive "$API_PID_FILE" && http_ready 'http://127.0.0.1:8010/api/system/ready'; then
    echo "API: EXISTING_MANAGED_READY_PROCESS"
    return 0
  fi

  if http_ready 'http://127.0.0.1:8010/api/system/ready'; then
    echo "API: UNMANAGED_PROCESS_OCCUPIES_8010" >&2
    echo "Refusing to claim a backend process that is not represented by the managed API PID file." >&2
    return 1
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
    --hostname="jobtomatik-android-${RUNTIME_REVISION_SHORT}@%h" \
    --loglevel=info \
    --pool=solo \
    --concurrency=1 \
    --without-gossip \
    --without-mingle \
    -Q applications,celery,followup,scraping \
    >"$CELERY_LOG" 2>&1 </dev/null &
  echo $! > "$CELERY_PID_FILE"

  if ! wait_worker; then
    echo "Celery failed the Android application-queue end-to-end canary." >&2
    tail -n 160 "$CELERY_LOG" >&2 || true
    return 1
  fi
  echo "CELERY: STARTED_WITH_REQUIRED_QUEUES"
  echo "CELERY_APPLICATION_CANARY: READY revision=$RUNTIME_REVISION_SHORT broker=$ANDROID_REDIS_URL"
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
    echo "API: READY pid=$(pid_file_value "$API_PID_FILE")"
  else
    echo "API: DOWN"
    failed=1
  fi

  if http_ready 'http://127.0.0.1:3000'; then
    echo "FRONTEND: READY pid=$(pid_file_value "$FRONTEND_PID_FILE")"
  else
    echo "FRONTEND: DOWN"
    failed=1
  fi

  if managed_worker_ready; then
    echo "CELERY: READY applications,celery,followup,scraping pid=$(pid_file_value "$CELERY_PID_FILE") broker=$ANDROID_REDIS_URL revision=$RUNTIME_REVISION_SHORT"
    echo "CELERY_APPLICATION_CANARY: READY"
  else
    echo "CELERY: DOWN_OR_UNRESPONSIVE_ON_ANDROID_BROKER"
    echo "CELERY_APPLICATION_CANARY: FAILED"
    failed=1
  fi

  if curl -fsS --max-time 2 'http://127.0.0.1:9222/json/version' 2>/dev/null | grep -q webSocketDebuggerUrl; then
    echo "ANDROID_BROWSER_CDP: READY"
  else
    echo "ANDROID_BROWSER_CDP: DOWN"
    failed=1
  fi

  local configured_redis
  configured_redis="$(configured_redis_url)"
  if [[ "$configured_redis" == "$ANDROID_REDIS_URL" ]]; then
    echo "ANDROID_RUNTIME_BROKER: ISOLATED"
  else
    echo "ANDROID_RUNTIME_BROKER: NOT_ISOLATED"
    failed=1
  fi
  echo "ANDROID_RUNTIME_REVISION: $RUNTIME_REVISION"
  echo "MANAGED_LOGS: $LOG_DIR"
  echo "CELERY_LOG: $CELERY_LOG"
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
  export JOBTOMATIK_RUNTIME_REVISION="$RUNTIME_REVISION"
  export JOBTOMATIK_RUNTIME_MODE='android_managed'

  if ! "$VENV/bin/python" -c 'import jwt; assert jwt.__version__' >/dev/null 2>&1; then
    "$VENV/bin/python" -m pip install --no-cache-dir 'PyJWT==2.13.0'
  fi

  if ! redis-cli ping 2>/dev/null | grep -q PONG; then
    redis-server --daemonize yes
    sleep 1
  fi

  # Retire only explicitly identified Celery workers through Celery remote control.
  # No terminal, shell, PRoot session, or unrelated process receives an OS signal.
  "$VENV/bin/python" scripts/retire_legacy_android_celery.py \
    --broker "$LEGACY_ANDROID_REDIS_URL" \
    --mode legacy \
    --timeout 1.0 \
    || true
  "$VENV/bin/python" scripts/retire_legacy_android_celery.py \
    --broker "$ANDROID_REDIS_URL" \
    --mode managed \
    --timeout 1.0 \
    || true

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

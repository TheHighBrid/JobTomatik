#!/usr/bin/env bash
set -euo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"
BACKEND_ROOT="$(cd -- "$(dirname -- "$SCRIPT_SOURCE")/.." && pwd)"
REPO_ROOT="$(cd -- "$BACKEND_ROOT/.." && pwd)"
FRONTEND_ROOT="$REPO_ROOT/frontend"
VENV="$BACKEND_ROOT/.venv"
ENV_FILE="$BACKEND_ROOT/.env"
RUNTIME_DIR="$BACKEND_ROOT/.runtime"
LOG_DIR="$RUNTIME_DIR/logs"
API_PID_FILE="$RUNTIME_DIR/api.pid"
CELERY_PID_FILE="$RUNTIME_DIR/celery.pid"
WORKER_CANARY_RECEIPT_FILE="$RUNTIME_DIR/celery-application-canary.json"
BEAT_PID_FILE="$RUNTIME_DIR/celery-beat.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
BEAT_IDENTITY_FILE="$RUNTIME_DIR/celery-beat-identity.json"
BEAT_SCHEDULE="$RUNTIME_DIR/celerybeat-schedule"
API_LOG="$LOG_DIR/api.log"
CELERY_LOG="$LOG_DIR/celery.log"
BEAT_LOG="$LOG_DIR/celery-beat.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
FRONTEND_GUARD="$BACKEND_ROOT/scripts/android_frontend_guard.sh"
STATIC_FRONTEND_SERVER="$BACKEND_ROOT/scripts/serve_static_frontend.py"
ACTION="${1:-start}"
ANDROID_REDIS_URL="${JOBTOMATIK_ANDROID_REDIS_URL:-redis://localhost:6379/1}"
LEGACY_ANDROID_REDIS_URL="${JOBTOMATIK_LEGACY_ANDROID_REDIS_URL:-redis://localhost:6379/0}"
RUNTIME_REVISION="${JOBTOMATIK_RUNTIME_REVISION:-$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)}"
RUNTIME_REVISION="${RUNTIME_REVISION,,}"
EXPECTED_RUNTIME_REVISION="${JOBTOMATIK_EXPECTED_REVISION:-$RUNTIME_REVISION}"
EXPECTED_RUNTIME_REVISION="${EXPECTED_RUNTIME_REVISION,,}"
RUNTIME_REVISION_SHORT="${RUNTIME_REVISION:0:12}"
WORKER_NODE_PREFIX="jobtomatik-android-${RUNTIME_REVISION_SHORT}@"
FRONTEND_RUNTIME_MODE="${JOBTOMATIK_FRONTEND_RUNTIME_MODE:-static_artifact}"
FRONTEND_ARTIFACT_ROOT="${JOBTOMATIK_FRONTEND_ARTIFACT_ROOT:-$RUNTIME_DIR/frontend-artifacts/$RUNTIME_REVISION}"
FRONTEND_DIST_ROOT="$FRONTEND_ARTIFACT_ROOT/dist"
FRONTEND_MANIFEST="$FRONTEND_ARTIFACT_ROOT/jobtomatik-frontend-manifest.json"

mkdir -p "$RUNTIME_DIR" "$LOG_DIR"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Backend virtual environment is missing at $VENV" >&2
  exit 1
fi

if [[ ! "$RUNTIME_REVISION" =~ ^[0-9a-f]{7,64}$ ]]; then
  echo "Unable to derive a valid JobTomatik Android runtime commit SHA." >&2
  exit 2
fi
if [[ ! "$EXPECTED_RUNTIME_REVISION" =~ ^[0-9a-f]{7,64}$ ]]; then
  echo "JOBTOMATIK_EXPECTED_REVISION is not a valid commit SHA." >&2
  exit 2
fi
if [[ "$EXPECTED_RUNTIME_REVISION" != "$RUNTIME_REVISION" ]]; then
  echo "JOBTOMATIK_EXPECTED_REVISION must equal the Android runtime revision." >&2
  exit 2
fi
if [[ "$FRONTEND_RUNTIME_MODE" != "static_artifact" ]]; then
  echo "Unsupported Android frontend runtime mode: $FRONTEND_RUNTIME_MODE" >&2
  echo "Android Runtime Architecture V2 requires JOBTOMATIK_FRONTEND_RUNTIME_MODE=static_artifact." >&2
  exit 2
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
  stop_pid_file "$BEAT_PID_FILE"
  rm -f "$BEAT_IDENTITY_FILE"
  rm -f "$WORKER_CANARY_RECEIPT_FILE"
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

frontend_guard() {
  local mode="$1"
  JOBTOMATIK_RUNTIME_REVISION="$RUNTIME_REVISION" \
  JOBTOMATIK_FRONTEND_ARTIFACT_ROOT="$FRONTEND_ARTIFACT_ROOT" \
    bash "$FRONTEND_GUARD" "$mode"
}

frontend_managed_ready() {
  frontend_guard status >/dev/null 2>&1
}

frontend_artifact_ready() {
  [[ -f "$FRONTEND_MANIFEST" ]] || return 1
  [[ -f "$FRONTEND_DIST_ROOT/index.html" ]] || return 1
  JOBTOMATIK_EXPECTED_FRONTEND_REVISION="$RUNTIME_REVISION" \
  JOBTOMATIK_FRONTEND_MANIFEST="$FRONTEND_MANIFEST" \
  "$VENV/bin/python" -c '
import json
import os
from pathlib import Path

manifest = json.loads(Path(os.environ["JOBTOMATIK_FRONTEND_MANIFEST"]).read_text(encoding="utf-8"))
valid = (
    manifest.get("version") == 1
    and manifest.get("artifact_type") == "jobtomatik-static-frontend"
    and manifest.get("revision") == os.environ["JOBTOMATIK_EXPECTED_FRONTEND_REVISION"]
    and manifest.get("build_api_url") == "http://127.0.0.1:8010"
    and bool(manifest.get("dist_tree_sha256"))
    and bool(manifest.get("package_lock_sha256"))
)
raise SystemExit(0 if valid else 1)
' >/dev/null 2>&1
}

configured_redis_url() {
  grep '^REDIS_URL=' "$ENV_FILE" 2>/dev/null | tail -n 1 | cut -d= -f2- || true
}

require_runtime_attestation() {
  local role="$1"
  (
    cd "$BACKEND_ROOT"
    JOBTOMATIK_RUNTIME_REVISION="$RUNTIME_REVISION" \
    JOBTOMATIK_EXPECTED_REVISION="$EXPECTED_RUNTIME_REVISION" \
    JOBTOMATIK_RUNTIME_ROLE="$role" \
    "$VENV/bin/python" scripts/check_runtime_identity.py --require-attested >/dev/null
  )
}

write_runtime_attestation_receipt() {
  local role="$1"
  local destination="$2"
  local temporary="${destination}.tmp"
  (
    cd "$BACKEND_ROOT"
    JOBTOMATIK_RUNTIME_REVISION="$RUNTIME_REVISION" \
    JOBTOMATIK_EXPECTED_REVISION="$EXPECTED_RUNTIME_REVISION" \
    JOBTOMATIK_RUNTIME_ROLE="$role" \
    "$VENV/bin/python" scripts/check_runtime_identity.py --require-attested >"$temporary"
  )
  mv "$temporary" "$destination"
}

api_runtime_identity_ready() {
  pid_file_alive "$API_PID_FILE" || return 1
  curl -fsS --max-time 2 'http://127.0.0.1:8010/api/system/runtime-identity' 2>/dev/null | \
    JOBTOMATIK_EXPECTED_RUNTIME_REVISION="$RUNTIME_REVISION" \
    JOBTOMATIK_EXPECTED_DEPLOYMENT_REVISION="$EXPECTED_RUNTIME_REVISION" \
    "$VENV/bin/python" -c '
import json
import os
import sys

payload = json.load(sys.stdin)
expected_runtime = os.environ["JOBTOMATIK_EXPECTED_RUNTIME_REVISION"]
expected_deployment = os.environ["JOBTOMATIK_EXPECTED_DEPLOYMENT_REVISION"]
valid = (
    payload.get("revision") == expected_runtime
    and payload.get("expected_revision") == expected_deployment
    and payload.get("role") == "api"
    and payload.get("deployment_attested") is True
    and bool(payload.get("identity_sha256"))
    and payload.get("submission_authorized") is False
    and payload.get("outreach_authorized") is False
)
raise SystemExit(0 if valid else 1)
' >/dev/null 2>&1
}

worker_process_identity_ready() {
  pid_file_alive "$CELERY_PID_FILE" || return 1
  local worker_pid
  worker_pid="$(pid_file_value "$CELERY_PID_FILE")"
  [[ "$worker_pid" =~ ^[0-9]+$ ]] || return 1

  JOBTOMATIK_EXPECTED_WORKER_PID="$worker_pid" \
  JOBTOMATIK_EXPECTED_WORKER_REVISION_SHORT="$RUNTIME_REVISION_SHORT" \
  JOBTOMATIK_EXPECTED_WORKER_QUEUES="applications,celery,followup,scraping" \
  "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import os
from pathlib import Path

pid = int(os.environ["JOBTOMATIK_EXPECTED_WORKER_PID"])
revision_short = os.environ["JOBTOMATIK_EXPECTED_WORKER_REVISION_SHORT"]
queues = os.environ["JOBTOMATIK_EXPECTED_WORKER_QUEUES"]
cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode(
    "utf-8", errors="replace"
)
required_tokens = (
    "celery",
    "app.celery_app",
    "worker",
    f"jobtomatik-android-{revision_short}@",
    "-Q",
    queues,
)
raise SystemExit(0 if all(token in cmdline for token in required_tokens) else 1)
PY
}

worker_application_canary_receipt_ready() {
  pid_file_alive "$CELERY_PID_FILE" || return 1
  [[ -f "$WORKER_CANARY_RECEIPT_FILE" ]] || return 1
  local broker
  local worker_pid
  broker="$(configured_redis_url)"
  worker_pid="$(pid_file_value "$CELERY_PID_FILE")"
  [[ "$broker" == "$ANDROID_REDIS_URL" ]] || return 1
  [[ "$worker_pid" =~ ^[0-9]+$ ]] || return 1

  (
    cd "$BACKEND_ROOT"
    JOBTOMATIK_RUNTIME_REVISION="$RUNTIME_REVISION" \
    JOBTOMATIK_EXPECTED_WORKER_PID="$worker_pid" \
    JOBTOMATIK_EXPECTED_WORKER_QUEUES="applications,celery,followup,scraping" \
    JOBTOMATIK_WORKER_CANARY_RECEIPT_FILE="$WORKER_CANARY_RECEIPT_FILE" \
    "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import os
from pathlib import Path

from app.services.android_worker_canary import validate_worker_canary_receipt

status = validate_worker_canary_receipt(
    Path(os.environ["JOBTOMATIK_WORKER_CANARY_RECEIPT_FILE"]),
    expected_revision=os.environ["JOBTOMATIK_RUNTIME_REVISION"],
    expected_worker_pid=int(os.environ["JOBTOMATIK_EXPECTED_WORKER_PID"]),
    required_queues=os.environ["JOBTOMATIK_EXPECTED_WORKER_QUEUES"].split(","),
)
raise SystemExit(0 if status.get("ok") else 1)
PY
  )
}

worker_application_canary_probe() {
  pid_file_alive "$CELERY_PID_FILE" || return 1
  local broker
  local worker_pid
  broker="$(configured_redis_url)"
  worker_pid="$(pid_file_value "$CELERY_PID_FILE")"
  [[ "$broker" == "$ANDROID_REDIS_URL" ]] || return 1
  [[ "$worker_pid" =~ ^[0-9]+$ ]] || return 1

  (
    cd "$BACKEND_ROOT"
    REDIS_URL="$broker" \
    JOBTOMATIK_RUNTIME_REVISION="$RUNTIME_REVISION" \
    JOBTOMATIK_EXPECTED_RUNTIME_REVISION="$EXPECTED_RUNTIME_REVISION" \
    JOBTOMATIK_EXPECTED_REDIS_DB="1" \
    JOBTOMATIK_EXPECTED_WORKER_PID="$worker_pid" \
    JOBTOMATIK_EXPECTED_WORKER_QUEUES="applications,celery,followup,scraping" \
    JOBTOMATIK_WORKER_CANARY_RECEIPT_FILE="$WORKER_CANARY_RECEIPT_FILE" \
    "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import os
from pathlib import Path

from app.services.android_worker_canary import write_worker_canary_receipt
from app.tasks.runtime import application_queue_canary

expected_revision = os.environ["JOBTOMATIK_RUNTIME_REVISION"]
expected_deployment = os.environ["JOBTOMATIK_EXPECTED_RUNTIME_REVISION"]
expected_db = int(os.environ.get("JOBTOMATIK_EXPECTED_REDIS_DB", "1"))
expected_worker_pid = int(os.environ["JOBTOMATIK_EXPECTED_WORKER_PID"])
declared_queues = os.environ["JOBTOMATIK_EXPECTED_WORKER_QUEUES"].split(",")
result = application_queue_canary.apply_async(
    kwargs={"expected_revision": expected_revision},
    queue="applications",
)
try:
    payload = result.get(timeout=60, propagate=True)
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
if payload.get("runtime_expected_revision") != expected_deployment:
    raise SystemExit(1)
if payload.get("runtime_role") != "worker":
    raise SystemExit(1)
if payload.get("deployment_attested") is not True:
    raise SystemExit(1)
if not payload.get("runtime_identity_sha256"):
    raise SystemExit(1)
if int(payload.get("worker_pid", -1)) != expected_worker_pid:
    raise SystemExit(1)

write_worker_canary_receipt(
    Path(os.environ["JOBTOMATIK_WORKER_CANARY_RECEIPT_FILE"]),
    payload=payload,
    expected_revision=expected_revision,
    expected_worker_pid=expected_worker_pid,
    declared_queues=declared_queues,
)
raise SystemExit(0)
PY
  )
}

managed_worker_ready() {
  worker_process_identity_ready && worker_application_canary_receipt_ready
}

wait_worker() {
  for _ in {1..120}; do
    if worker_process_identity_ready; then
      if worker_application_canary_receipt_ready; then
        return 0
      fi
      if worker_application_canary_probe && worker_application_canary_receipt_ready; then
        return 0
      fi
      return 1
    fi
    if [[ -f "$CELERY_PID_FILE" ]] && ! pid_file_alive "$CELERY_PID_FILE"; then
      return 1
    fi
    sleep 1
  done
  return 1
}

beat_schedule_contract_ready() {
  local broker
  broker="$(configured_redis_url)"
  [[ "$broker" == "$ANDROID_REDIS_URL" ]] || return 1
  (
    cd "$BACKEND_ROOT"
    REDIS_URL="$broker" \
    "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
from app.celery_app import celery_app

entry = dict(celery_app.conf.beat_schedule or {}).get("recover-stalled-shadow-campaigns")
if not isinstance(entry, dict):
    raise SystemExit(1)
if entry.get("task") != "app.tasks.shadow_runs.recover_stalled_shadow_sessions":
    raise SystemExit(1)
schedule = entry.get("schedule")
minutes = set(getattr(schedule, "minute", set()) or set())
if minutes != {11, 26, 41, 56}:
    raise SystemExit(1)
raise SystemExit(0)
PY
  )
}

beat_identity_receipt_ready() {
  pid_file_alive "$BEAT_PID_FILE" || return 1
  [[ -f "$BEAT_IDENTITY_FILE" ]] || return 1
  JOBTOMATIK_EXPECTED_RUNTIME_REVISION="$RUNTIME_REVISION" \
  JOBTOMATIK_EXPECTED_DEPLOYMENT_REVISION="$EXPECTED_RUNTIME_REVISION" \
  "$VENV/bin/python" - "$BEAT_IDENTITY_FILE" <<'PY' >/dev/null 2>&1
import json
import os
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    payload = json.load(handle)
valid = (
    payload.get("revision") == os.environ["JOBTOMATIK_EXPECTED_RUNTIME_REVISION"]
    and payload.get("expected_revision") == os.environ["JOBTOMATIK_EXPECTED_DEPLOYMENT_REVISION"]
    and payload.get("role") == "beat"
    and payload.get("deployment_attested") is True
    and payload.get("configuration_valid") is True
    and bool(payload.get("identity_sha256"))
    and payload.get("submission_authorized") is False
    and payload.get("outreach_authorized") is False
)
raise SystemExit(0 if valid else 1)
PY
}

managed_beat_ready() {
  beat_identity_receipt_ready && beat_schedule_contract_ready
}

wait_beat() {
  local stable_checks=0
  for _ in {1..40}; do
    if managed_beat_ready; then
      stable_checks=$((stable_checks + 1))
      if [[ "$stable_checks" -ge 4 ]]; then
        return 0
      fi
    else
      stable_checks=0
    fi
    if [[ -f "$BEAT_PID_FILE" ]] && ! pid_file_alive "$BEAT_PID_FILE"; then
      return 1
    fi
    sleep 0.5
  done
  return 1
}

start_api() {
  if pid_file_alive "$API_PID_FILE" && http_ready 'http://127.0.0.1:8010/api/system/ready'; then
    if api_runtime_identity_ready; then
      echo "API: EXISTING_MANAGED_READY_PROCESS"
      return 0
    fi
    echo "API: STALE_OR_UNATTESTED_MANAGED_PROCESS_RESTARTING"
    stop_pid_file "$API_PID_FILE"
  fi

  if http_ready 'http://127.0.0.1:8010/api/system/ready'; then
    echo "API: UNMANAGED_PROCESS_OCCUPIES_8010" >&2
    echo "Refusing to claim a backend process that is not represented by the managed API PID file." >&2
    return 1
  fi

  stop_pid_file "$API_PID_FILE"
  require_runtime_attestation api
  : > "$API_LOG"
  nohup env -i \
    PATH="$PATH" \
    HOME="${HOME:-/tmp}" \
    JOBTOMATIK_RUNTIME_MODE=android_managed \
    JOBTOMATIK_RUNTIME_REVISION="$RUNTIME_REVISION" \
    JOBTOMATIK_EXPECTED_REVISION="$EXPECTED_RUNTIME_REVISION" \
    JOBTOMATIK_RUNTIME_ROLE=api \
    "$VENV/bin/uvicorn" app.main:app \
    --host 127.0.0.1 \
    --port 8010 \
    >"$API_LOG" 2>&1 </dev/null &
  echo $! > "$API_PID_FILE"

  if ! wait_http 'http://127.0.0.1:8010/api/system/ready' 120; then
    echo "API failed to become ready." >&2
    tail -n 100 "$API_LOG" >&2 || true
    return 1
  fi
  if ! api_runtime_identity_ready; then
    echo "API became reachable but failed exact runtime-attestation verification." >&2
    tail -n 100 "$API_LOG" >&2 || true
    stop_pid_file "$API_PID_FILE"
    return 1
  fi
  echo "API: STARTED_ATTESTED revision=$RUNTIME_REVISION_SHORT"
}

start_worker() {
  if managed_worker_ready; then
    echo "CELERY: EXISTING_MANAGED_WORKER_READY"
    return 0
  fi
  rm -f "$WORKER_CANARY_RECEIPT_FILE"
  stop_pid_file "$CELERY_PID_FILE"
  require_runtime_attestation worker
  : > "$CELERY_LOG"
  nohup env -i \
    PATH="$PATH" \
    HOME="${HOME:-/tmp}" \
    JOBTOMATIK_RUNTIME_MODE=android_managed \
    JOBTOMATIK_RUNTIME_REVISION="$RUNTIME_REVISION" \
    JOBTOMATIK_EXPECTED_REVISION="$EXPECTED_RUNTIME_REVISION" \
    JOBTOMATIK_RUNTIME_ROLE=worker \
    "$VENV/bin/celery" -A app.celery_app worker \
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
    echo "Celery failed the Android startup application-queue proof or runtime-attestation check." >&2
    tail -n 160 "$CELERY_LOG" >&2 || true
    return 1
  fi
  echo "CELERY: STARTED_WITH_REQUIRED_QUEUES_ATTESTED"
  echo "CELERY_APPLICATION_CANARY: READY revision=$RUNTIME_REVISION_SHORT broker=$ANDROID_REDIS_URL source=startup_receipt"
}

start_beat() {
  if managed_beat_ready; then
    echo "CELERY_BEAT: EXISTING_MANAGED_READY_PROCESS"
    return 0
  fi

  stop_pid_file "$BEAT_PID_FILE"
  rm -f "$BEAT_IDENTITY_FILE"
  require_runtime_attestation beat
  beat_schedule_contract_ready
  write_runtime_attestation_receipt beat "$BEAT_IDENTITY_FILE"
  : > "$BEAT_LOG"
  nohup env -i \
    PATH="$PATH" \
    HOME="${HOME:-/tmp}" \
    REDIS_URL="$ANDROID_REDIS_URL" \
    JOBTOMATIK_RUNTIME_MODE=android_managed \
    JOBTOMATIK_RUNTIME_REVISION="$RUNTIME_REVISION" \
    JOBTOMATIK_EXPECTED_REVISION="$EXPECTED_RUNTIME_REVISION" \
    JOBTOMATIK_RUNTIME_ROLE=beat \
    "$VENV/bin/celery" -A app.celery_app beat \
    --loglevel=info \
    --schedule="$BEAT_SCHEDULE" \
    >"$BEAT_LOG" 2>&1 </dev/null &
  echo $! > "$BEAT_PID_FILE"

  if ! wait_beat; then
    echo "Celery Beat failed exact runtime-attestation or shadow-recovery schedule readiness." >&2
    tail -n 120 "$BEAT_LOG" >&2 || true
    stop_pid_file "$BEAT_PID_FILE"
    rm -f "$BEAT_IDENTITY_FILE"
    return 1
  fi
  echo "CELERY_BEAT: STARTED_ATTESTED shadow-recovery=11,26,41,56"
}

start_frontend() {
  if ! frontend_artifact_ready; then
    echo "Static frontend artifact is missing or does not attest revision $RUNTIME_REVISION." >&2
    echo "Run the Termux wrapper so it can install the exact GitHub Actions artifact before stack start." >&2
    return 1
  fi

  if frontend_managed_ready; then
    echo "FRONTEND: EXISTING_STATIC_ATTESTED pid=$(pid_file_value "$FRONTEND_PID_FILE") revision=$RUNTIME_REVISION_SHORT"
    return 0
  fi

  if http_ready 'http://127.0.0.1:3000'; then
    echo "FRONTEND: UNMANAGED_OR_STALE_PROCESS_RETIRING"
    if ! frontend_guard reset; then
      echo "Frontend port 3000 is occupied by a process that cannot be safely identified as JobTomatik." >&2
      return 1
    fi
  fi

  stop_pid_file "$FRONTEND_PID_FILE"
  : > "$FRONTEND_LOG"
  cd "$FRONTEND_ARTIFACT_ROOT"
  nohup env \
    JOBTOMATIK_RUNTIME_REVISION="$RUNTIME_REVISION" \
    "$VENV/bin/python" "$STATIC_FRONTEND_SERVER" \
    --root "$FRONTEND_DIST_ROOT" \
    --manifest "$FRONTEND_MANIFEST" \
    --revision "$RUNTIME_REVISION" \
    --host 127.0.0.1 \
    --port 3000 \
    >"$FRONTEND_LOG" 2>&1 </dev/null &
  echo $! > "$FRONTEND_PID_FILE"

  if ! wait_http 'http://127.0.0.1:3000' 120; then
    echo "Static frontend failed to become ready." >&2
    tail -n 100 "$FRONTEND_LOG" >&2 || true
    stop_pid_file "$FRONTEND_PID_FILE"
    return 1
  fi
  if ! frontend_managed_ready; then
    echo "Static frontend became reachable but failed exact artifact/process attestation." >&2
    tail -n 100 "$FRONTEND_LOG" >&2 || true
    stop_pid_file "$FRONTEND_PID_FILE"
    return 1
  fi
  echo "FRONTEND: STARTED_STATIC_ATTESTED pid=$(pid_file_value "$FRONTEND_PID_FILE") revision=$RUNTIME_REVISION_SHORT"
}

refresh_frontend_runtime() {
  cd "$BACKEND_ROOT"
  "$VENV/bin/python" scripts/refresh_android_jobtomatik_tabs.py
}

status_stack() {
  local failed=0
  local api_attested=0
  local worker_attested=0
  local beat_attested=0
  local frontend_managed=0

  if http_ready 'http://127.0.0.1:8010/api/system/ready'; then
    if api_runtime_identity_ready; then
      echo "API: READY_ATTESTED pid=$(pid_file_value "$API_PID_FILE") revision=$RUNTIME_REVISION_SHORT"
      api_attested=1
    else
      echo "API: READY_BUT_RUNTIME_IDENTITY_UNATTESTED_OR_STALE"
      failed=1
    fi
  else
    echo "API: DOWN"
    failed=1
  fi

  if frontend_managed_ready; then
    echo "FRONTEND: READY_STATIC_ATTESTED pid=$(pid_file_value "$FRONTEND_PID_FILE") revision=$RUNTIME_REVISION_SHORT"
    frontend_managed=1
  elif http_ready 'http://127.0.0.1:3000'; then
    echo "FRONTEND: READY_BUT_UNMANAGED_OR_STALE"
    failed=1
  else
    echo "FRONTEND: DOWN"
    failed=1
  fi

  if managed_worker_ready; then
    echo "CELERY: READY applications,celery,followup,scraping pid=$(pid_file_value "$CELERY_PID_FILE") broker=$ANDROID_REDIS_URL revision=$RUNTIME_REVISION_SHORT"
    echo "CELERY_APPLICATION_CANARY: STARTUP_RECEIPT_ATTESTED"
    worker_attested=1
  else
    echo "CELERY: DOWN_OR_UNATTESTED_STARTUP_PROOF"
    echo "CELERY_APPLICATION_CANARY: STARTUP_RECEIPT_FAILED"
    failed=1
  fi

  if managed_beat_ready; then
    echo "CELERY_BEAT: READY_ATTESTED pid=$(pid_file_value "$BEAT_PID_FILE") shadow-recovery=11,26,41,56"
    beat_attested=1
  else
    echo "CELERY_BEAT: DOWN_OR_UNATTESTED"
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

  if [[ "$api_attested" -eq 1 && "$worker_attested" -eq 1 && "$beat_attested" -eq 1 && "$frontend_managed" -eq 1 ]]; then
    echo "ANDROID_RUNTIME_ATTESTATION: READY runtime=$RUNTIME_REVISION expected=$EXPECTED_RUNTIME_REVISION frontend=static_artifact"
  else
    echo "ANDROID_RUNTIME_ATTESTATION: FAILED runtime=$RUNTIME_REVISION expected=$EXPECTED_RUNTIME_REVISION frontend=static_artifact"
    failed=1
  fi

  echo "ANDROID_RUNTIME_REVISION: $RUNTIME_REVISION"
  echo "ANDROID_EXPECTED_REVISION: $EXPECTED_RUNTIME_REVISION"
  echo "ANDROID_FRONTEND_RUNTIME_MODE: $FRONTEND_RUNTIME_MODE"
  echo "ANDROID_FRONTEND_ARTIFACT_ROOT: $FRONTEND_ARTIFACT_ROOT"
  echo "MANAGED_LOGS: $LOG_DIR"
  echo "CELERY_LOG: $CELERY_LOG"
  echo "CELERY_BEAT_LOG: $BEAT_LOG"
  return "$failed"
}

prepare_stack() {
  cd "$BACKEND_ROOT"

  if ! frontend_artifact_ready; then
    echo "ANDROID_STATIC_FRONTEND_ARTIFACT_MISSING revision=$RUNTIME_REVISION" >&2
    return 1
  fi

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
  export JOBTOMATIK_EXPECTED_REVISION="$EXPECTED_RUNTIME_REVISION"
  export JOBTOMATIK_RUNTIME_MODE='android_managed'
  export JOBTOMATIK_FRONTEND_RUNTIME_MODE="$FRONTEND_RUNTIME_MODE"
  export JOBTOMATIK_FRONTEND_ARTIFACT_ROOT="$FRONTEND_ARTIFACT_ROOT"

  require_runtime_attestation cli

  if ! "$VENV/bin/python" -c 'import jwt; assert jwt.__version__' >/dev/null 2>&1; then
    "$VENV/bin/python" -m pip install --no-cache-dir 'PyJWT==2.13.0'
  fi

  if ! redis-cli ping 2>/dev/null | grep -q PONG; then
    redis-server --daemonize yes
    sleep 1
  fi

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
  start_beat
  start_frontend
  refresh_frontend_runtime

  cd "$BACKEND_ROOT"
  status_stack
  echo "JOBTOMATIK_ANDROID_STACK_READY"
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

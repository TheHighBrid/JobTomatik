#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ACTION="${1:-status}"
PROOT_DISTRO="${JOBTOMATIK_PROOT_DISTRO:-ubuntu}"
FROZEN_REPO="${JOBTOMATIK_FROZEN_PROOT_REPO:-/root/JobTomatik}"
PROMOTION_REPO="${JOBTOMATIK_PROMOTION_PROOT_REPO:-/root/JobTomatik-promotion}"
EXPECTED_FROZEN_REVISION="${JOBTOMATIK_FROZEN_REVISION:-}"
SOURCE_REVISION_PIN_MODE="explicit"
STACK_COMMAND="${JOBTOMATIK_STACK_COMMAND:-jobtomatik}"
PILOT_COMMAND="${JOBTOMATIK_PILOT_COMMAND:-jobtomatik-pilot}"
FROZEN_RUNTIME_DIR="${JOBTOMATIK_FROZEN_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"
PROMOTION_RUNTIME_DIR="${JOBTOMATIK_PROMOTION_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-promotion-runtime}"
FROZEN_BROWSER_PROFILE="${JOBTOMATIK_FROZEN_ANDROID_BROWSER_PROFILE:-$HOME/.jobtomatik-chromium}"
PROMOTION_BROWSER_PROFILE="${JOBTOMATIK_PROMOTION_ANDROID_BROWSER_PROFILE:-$HOME/.jobtomatik-promotion-chromium}"
PROMOTION_DEPLOYMENT_MARKER="${JOBTOMATIK_PROMOTION_DEPLOYMENT_RESTART_MARKER:-$PROMOTION_RUNTIME_DIR/deployment-restart.pending}"
FROZEN_REDIS_URL="${JOBTOMATIK_FROZEN_ANDROID_REDIS_URL:-redis://localhost:6379/1}"
PROMOTION_REDIS_PORT="${JOBTOMATIK_PROMOTION_REDIS_PORT:-6380}"
PROMOTION_REDIS_DB="${JOBTOMATIK_PROMOTION_REDIS_DB:-1}"
PROMOTION_REDIS_URL="${JOBTOMATIK_PROMOTION_ANDROID_REDIS_URL:-redis://localhost:${PROMOTION_REDIS_PORT}/${PROMOTION_REDIS_DB}}"
PROMOTION_REDIS_PID_FILE="$PROMOTION_RUNTIME_DIR/redis-server.pid"
NATIVE_TMPDIR="${TMPDIR:-${PREFIX:-/data/data/com.termux/files/usr}/tmp}"
SHARED_CONTROL_DIR="${JOBTOMATIK_SHARED_PILOT_CONTROL_DIR:-$NATIVE_TMPDIR/jobtomatik-pilot-control}"
MIN_FREE_KB="${JOBTOMATIK_PROMOTION_MIN_FREE_KB:-262144}"
PROOT_COMMAND=""
REDIS_SERVER_BIN=""
REDIS_CLI_BIN=""
BROWSER_COMMAND=""
PILOT_CONTROLLER_COMMAND=""
PILOT_CONTROLLER_MANAGER_COMMAND=""
PROCESS_IDENTITY_HELPER=""

NATIVE_CONTRACT_PATHS=(
  backend/scripts/jobtomatik_termux_wrapper.sh
  backend/scripts/jobtomatik_pilot_wrapper.sh
  backend/scripts/jobtomatik_pilot_control_daemon.sh
  backend/scripts/jobtomatik_pilot_controller_manager.sh
  backend/scripts/start_android_browser_cdp.sh
  backend/scripts/jobtomatik_process_identity.sh
)

require_native_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Required native command is unavailable: $name" >&2
    exit 1
  fi
}

resolve_source_revision() {
  if [[ -n "$EXPECTED_FROZEN_REVISION" ]]; then
    if [[ ! "$EXPECTED_FROZEN_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
      echo "JOBTOMATIK_FROZEN_REVISION must be a full 40-character commit SHA." >&2
      exit 2
    fi
    SOURCE_REVISION_PIN_MODE="explicit"
    return 0
  fi

  EXPECTED_FROZEN_REVISION="$(
    "$PROOT_COMMAND" login "$PROOT_DISTRO" --shared-tmp -- bash -s -- "$FROZEN_REPO" <<'GUEST'
set -euo pipefail
repo="$1"
git -C "$repo" rev-parse HEAD
GUEST
  )"
  if [[ ! "$EXPECTED_FROZEN_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Unable to capture a valid source checkout revision from $FROZEN_REPO." >&2
    exit 2
  fi
  SOURCE_REVISION_PIN_MODE="captured_at_invocation"
}

promotion_redis_identity_matches() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [[ -r "/proc/$pid/cmdline" ]] || return 1
  local cmdline
  cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  [[ "$cmdline" == *"redis-server"* && "$cmdline" == *":${PROMOTION_REDIS_PORT}"* ]]
}

promotion_redis_ready() {
  [[ "$PROMOTION_REDIS_PORT" =~ ^[0-9]+$ ]] || return 1
  [[ "$PROMOTION_REDIS_DB" =~ ^[0-9]+$ ]] || return 1
  [[ "$($REDIS_CLI_BIN -h 127.0.0.1 -p "$PROMOTION_REDIS_PORT" -n "$PROMOTION_REDIS_DB" ping 2>/dev/null || true)" == "PONG" ]]
}

start_promotion_redis() {
  mkdir -p "$PROMOTION_RUNTIME_DIR"
  if promotion_redis_ready; then
    local existing_pid=""
    existing_pid="$(cat "$PROMOTION_REDIS_PID_FILE" 2>/dev/null || true)"
    if ! promotion_redis_identity_matches "$existing_pid"; then
      echo "Port $PROMOTION_REDIS_PORT is occupied by an unmanaged Redis process; refusing promotion startup." >&2
      return 1
    fi
  else
    rm -f "$PROMOTION_REDIS_PID_FILE"
    "$REDIS_SERVER_BIN" \
      --bind 127.0.0.1 \
      --protected-mode yes \
      --port "$PROMOTION_REDIS_PORT" \
      --daemonize yes \
      --pidfile "$PROMOTION_REDIS_PID_FILE" \
      --dir "$PROMOTION_RUNTIME_DIR" \
      --dbfilename promotion-redis.rdb \
      --appendonly no
    for _ in {1..50}; do
      promotion_redis_ready && break
      sleep 0.2
    done
    if ! promotion_redis_ready; then
      echo "Promotion Redis failed to become ready on port $PROMOTION_REDIS_PORT." >&2
      return 1
    fi
    local started_pid=""
    started_pid="$(cat "$PROMOTION_REDIS_PID_FILE" 2>/dev/null || true)"
    if ! promotion_redis_identity_matches "$started_pid"; then
      echo "Promotion Redis PID identity verification failed." >&2
      return 1
    fi
  fi

  "$REDIS_CLI_BIN" -h 127.0.0.1 -p "$PROMOTION_REDIS_PORT" -n "$PROMOTION_REDIS_DB" FLUSHDB >/dev/null
  echo "JOBTOMATIK_PROMOTION_REDIS_READY url=$PROMOTION_REDIS_URL"
}

stop_promotion_redis() {
  local pid=""
  pid="$(cat "$PROMOTION_REDIS_PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    if ! promotion_redis_identity_matches "$pid"; then
      echo "Promotion Redis PID file is stale; unrelated process was not signaled." >&2
      return 1
    fi
    kill -TERM "$pid" 2>/dev/null || return 1
    for _ in {1..30}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "Promotion Redis did not stop cleanly; refusing to claim containment." >&2
      return 1
    fi
  fi
  rm -f "$PROMOTION_REDIS_PID_FILE"
}

promotion_stack() {
  JOBTOMATIK_PROOT_REPO="$PROMOTION_REPO" \
  JOBTOMATIK_ANDROID_RUNTIME_DIR="$PROMOTION_RUNTIME_DIR" \
  JOBTOMATIK_ANDROID_BROWSER_PROFILE="$PROMOTION_BROWSER_PROFILE" \
  JOBTOMATIK_DEPLOYMENT_RESTART_MARKER="$PROMOTION_DEPLOYMENT_MARKER" \
  JOBTOMATIK_ANDROID_REDIS_URL="$PROMOTION_REDIS_URL" \
  JOBTOMATIK_BROWSER_COMMAND="$BROWSER_COMMAND" \
  JOBTOMATIK_PILOT_CONTROLLER_MANAGER="$PILOT_CONTROLLER_MANAGER_COMMAND" \
  JOBTOMATIK_PROCESS_IDENTITY_HELPER="$PROCESS_IDENTITY_HELPER" \
    "$STACK_COMMAND" "$@"
}

promotion_pilot() {
  JOBTOMATIK_PROOT_REPO="$PROMOTION_REPO" \
  JOBTOMATIK_ANDROID_RUNTIME_DIR="$PROMOTION_RUNTIME_DIR" \
  JOBTOMATIK_ANDROID_BROWSER_PROFILE="$PROMOTION_BROWSER_PROFILE" \
  JOBTOMATIK_DEPLOYMENT_RESTART_MARKER="$PROMOTION_DEPLOYMENT_MARKER" \
  JOBTOMATIK_ANDROID_REDIS_URL="$PROMOTION_REDIS_URL" \
  JOBTOMATIK_STACK_COMMAND="$STACK_COMMAND" \
  JOBTOMATIK_PILOT_CONTROLLER_COMMAND="$PILOT_CONTROLLER_COMMAND" \
  JOBTOMATIK_PROCESS_IDENTITY_HELPER="$PROCESS_IDENTITY_HELPER" \
    "$PILOT_COMMAND" "$@"
}

frozen_stack() {
  JOBTOMATIK_PROOT_REPO="$FROZEN_REPO" \
  JOBTOMATIK_ANDROID_RUNTIME_DIR="$FROZEN_RUNTIME_DIR" \
  JOBTOMATIK_ANDROID_BROWSER_PROFILE="$FROZEN_BROWSER_PROFILE" \
  JOBTOMATIK_ANDROID_REDIS_URL="$FROZEN_REDIS_URL" \
  JOBTOMATIK_BROWSER_COMMAND="$BROWSER_COMMAND" \
  JOBTOMATIK_PILOT_CONTROLLER_MANAGER="$PILOT_CONTROLLER_MANAGER_COMMAND" \
  JOBTOMATIK_PROCESS_IDENTITY_HELPER="$PROCESS_IDENTITY_HELPER" \
    "$STACK_COMMAND" "$@"
}

archive_shared_control_dir() {
  local owner_runtime="$1"
  local label="$2"
  local stamp archive_root destination
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive_root="$owner_runtime/pilot-control-archives"
  mkdir -p "$archive_root"
  if [[ -d "$SHARED_CONTROL_DIR" ]]; then
    destination="$archive_root/${label}-${stamp}"
    mv "$SHARED_CONTROL_DIR" "$destination"
    echo "JOBTOMATIK_PROMOTION_CONTROL_ARCHIVED=$destination"
  fi
  mkdir -p "$SHARED_CONTROL_DIR"
  chmod 700 "$SHARED_CONTROL_DIR" 2>/dev/null || true
}

verify_frozen_return_artifact() {
  "$PROOT_COMMAND" login "$PROOT_DISTRO" --shared-tmp -- bash -s -- \
    "$FROZEN_REPO" "$EXPECTED_FROZEN_REVISION" <<'GUEST'
set -euo pipefail
repo="$1"
expected="$2"
actual="$(git -C "$repo" rev-parse HEAD)"
if [[ "$actual" != "$expected" ]]; then
  echo "Frozen checkout moved: expected=$expected actual=$actual" >&2
  exit 1
fi
cd "$repo"
backend/.venv/bin/python backend/scripts/install_android_static_frontend_artifact.py \
  --wait-seconds 0 >/dev/null
GUEST
  echo "JOBTOMATIK_FROZEN_RETURN_ARTIFACT_VERIFIED=$EXPECTED_FROZEN_REVISION"
}

expected_contract_digest() {
  local source_path="$1"
  "$PROOT_COMMAND" login "$PROOT_DISTRO" --shared-tmp -- bash -s -- \
    "$FROZEN_REPO" "$EXPECTED_FROZEN_REVISION" "$source_path" <<'GUEST'
set -euo pipefail
repo="$1"
expected="$2"
path="$3"
actual="$(git -C "$repo" rev-parse HEAD)"
if [[ "$actual" != "$expected" ]]; then
  echo "Frozen checkout moved during native contract attestation." >&2
  exit 1
fi
git -C "$repo" show "$expected:$path" | sha256sum | awk '{print $1}'
GUEST
}

verify_installed_native_contracts() {
  local installed_paths=(
    "$STACK_COMMAND"
    "$PILOT_COMMAND"
    "$PILOT_CONTROLLER_COMMAND"
    "$PILOT_CONTROLLER_MANAGER_COMMAND"
    "$BROWSER_COMMAND"
    "$PROCESS_IDENTITY_HELPER"
  )
  local index source_path installed_path expected_digest observed_digest
  for index in "${!NATIVE_CONTRACT_PATHS[@]}"; do
    source_path="${NATIVE_CONTRACT_PATHS[$index]}"
    installed_path="${installed_paths[$index]}"
    if [[ ! -f "$installed_path" ]]; then
      echo "Installed native launcher is missing: $installed_path" >&2
      return 1
    fi
    expected_digest="$(expected_contract_digest "$source_path")"
    observed_digest="$(sha256sum "$installed_path" | awk '{print $1}')"
    if [[ -z "$expected_digest" || "$observed_digest" != "$expected_digest" ]]; then
      echo "Installed native launcher drift detected: $installed_path source=$source_path" >&2
      return 1
    fi
  done
  echo "JOBTOMATIK_PROMOTION_NATIVE_CONTRACTS_ATTESTED=$EXPECTED_FROZEN_REVISION"
}

prepare_lane() {
  "$PROOT_COMMAND" login "$PROOT_DISTRO" --shared-tmp -- bash -s -- \
    "$FROZEN_REPO" "$PROMOTION_REPO" "$EXPECTED_FROZEN_REVISION" "$MIN_FREE_KB" \
    "${NATIVE_CONTRACT_PATHS[@]}" <<'GUEST'
set -euo pipefail

source_repo="$1"
promotion_repo="$2"
expected_frozen="$3"
min_free_kb="$4"
shift 4
native_paths=("$@")
marker_rel="backend/.runtime/promotion-lane.json"

if [[ ! -d "$source_repo/.git" && ! -f "$source_repo/.git" ]]; then
  echo "Frozen repository is not a Git checkout: $source_repo" >&2
  exit 1
fi
source_head="$(git -C "$source_repo" rev-parse HEAD)"
if [[ "$source_head" != "$expected_frozen" ]]; then
  echo "Frozen certification checkout must remain exact: expected=$expected_frozen actual=$source_head" >&2
  exit 1
fi
if ! git -C "$source_repo" diff --quiet || ! git -C "$source_repo" diff --cached --quiet; then
  echo "Frozen checkout has tracked modifications; refusing to use it as promotion-lane source." >&2
  exit 1
fi
if [[ ! -x "$source_repo/backend/.venv/bin/python" ]]; then
  echo "Frozen backend virtualenv is missing." >&2
  exit 1
fi
if [[ ! -f "$source_repo/backend/.env" ]]; then
  echo "Frozen backend .env is missing." >&2
  exit 1
fi

git -C "$source_repo" fetch --no-tags origin main
target_revision="$(git -C "$source_repo" rev-parse origin/main)"

if ! git -C "$source_repo" cat-file -e "$source_head:backend/requirements.txt" 2>/dev/null; then
  echo "Frozen revision is missing required contract file: backend/requirements.txt" >&2
  exit 1
fi
if ! git -C "$source_repo" cat-file -e "$target_revision:backend/requirements.txt" 2>/dev/null; then
  echo "Promotion revision is missing required contract file: backend/requirements.txt" >&2
  exit 1
fi
source_requirements="$(git -C "$source_repo" rev-parse "$source_head:backend/requirements.txt")"
target_requirements="$(git -C "$source_repo" rev-parse "$target_revision:backend/requirements.txt")"
if [[ "$source_requirements" != "$target_requirements" ]]; then
  echo "backend/requirements.txt changed since the frozen runtime; refusing to share its virtualenv." >&2
  exit 1
fi

for path in "${native_paths[@]}"; do
  if ! git -C "$source_repo" cat-file -e "$source_head:$path" 2>/dev/null; then
    echo "Frozen revision is missing native launcher contract file: $path" >&2
    exit 1
  fi
  if ! git -C "$source_repo" cat-file -e "$target_revision:$path" 2>/dev/null; then
    echo "Promotion revision is missing native launcher contract file: $path" >&2
    exit 1
  fi
  source_blob="$(git -C "$source_repo" rev-parse "$source_head:$path")"
  target_blob="$(git -C "$source_repo" rev-parse "$target_revision:$path")"
  if [[ "$source_blob" != "$target_blob" ]]; then
    echo "Native launcher contract changed at $path; install/update review is required before promotion-lane reuse." >&2
    exit 1
  fi
done

if [[ -e "$promotion_repo" ]]; then
  marker="$promotion_repo/$marker_rel"
  if [[ ! -f "$marker" ]]; then
    echo "Promotion path already exists without a verified lane marker: $promotion_repo" >&2
    exit 1
  fi
  existing_target="$(git -C "$promotion_repo" rev-parse HEAD)"
  if [[ "$existing_target" != "$target_revision" ]]; then
    echo "Existing promotion lane is not current main: lane=$existing_target current=$target_revision" >&2
    echo "Refusing implicit upgrade. Return to frozen and rebuild the isolated lane explicitly." >&2
    exit 1
  fi
  (
    cd "$promotion_repo/backend"
    .venv/bin/python scripts/prepare_lever_promotion_lane_state.py verify \
      --promotion-repo "$promotion_repo" \
      --expected-frozen-revision "$expected_frozen" \
      --expected-target-revision "$target_revision"
  )
  echo "JOBTOMATIK_PROMOTION_LANE_ALREADY_PREPARED=$target_revision"
  exit 0
fi

free_kb="$(df -Pk "$(dirname "$promotion_repo")" | awk 'NR==2 {print $4}')"
if [[ ! "$free_kb" =~ ^[0-9]+$ ]] || (( free_kb < min_free_kb )); then
  echo "Insufficient free space for isolated promotion worktree: free_kb=${free_kb:-unknown} required_kb=$min_free_kb" >&2
  exit 1
fi

git -C "$source_repo" worktree add --detach "$promotion_repo" "$target_revision"
created=1
cleanup_partial() {
  if [[ "${created:-0}" == "1" ]]; then
    git -C "$source_repo" worktree remove --force "$promotion_repo" >/dev/null 2>&1 || {
      rm -rf "$promotion_repo"
      git -C "$source_repo" worktree prune >/dev/null 2>&1 || true
    }
  fi
}
trap cleanup_partial ERR INT TERM HUP
ln -s "$source_repo/backend/.venv" "$promotion_repo/backend/.venv"
(
  cd "$promotion_repo"
  backend/.venv/bin/python backend/scripts/verify_python_environment_requirements.py \
    --requirements backend/requirements.txt
)
(
  cd "$promotion_repo/backend"
  .venv/bin/python scripts/prepare_lever_promotion_lane_state.py prepare \
    --source-repo "$source_repo" \
    --promotion-repo "$promotion_repo" \
    --source-revision "$source_head" \
    --target-revision "$target_revision"
)
created=0
trap - ERR INT TERM HUP
echo "JOBTOMATIK_PROMOTION_LANE_PREPARED=$target_revision"
GUEST
}

contain_promotion_stack() {
  local label="$1"
  if ! promotion_stack stop; then
    echo "Promotion stack stop failed during $label; frozen lane remains blocked." >&2
    return 1
  fi
  if ! stop_promotion_redis; then
    echo "Promotion Redis stop failed during $label; frozen lane remains blocked." >&2
    return 1
  fi
  archive_shared_control_dir "$PROMOTION_RUNTIME_DIR" "$label"
}

restore_frozen_after_failure() {
  local label="$1"
  contain_promotion_stack "$label" || return 1
  frozen_stack start || return 1
}

start_lane() {
  verify_installed_native_contracts
  prepare_lane
  verify_frozen_return_artifact
  if ! promotion_stack stop; then
    echo "Unable to prove the prior promotion stack is stopped; leaving frozen lane untouched." >&2
    exit 1
  fi
  stop_promotion_redis
  frozen_stack stop
  archive_shared_control_dir "$FROZEN_RUNTIME_DIR" "before-promotion"

  if ! start_promotion_redis; then
    echo "Promotion Redis failed to start; restoring frozen lane." >&2
    stop_promotion_redis || true
    frozen_stack start || true
    exit 1
  fi
  if ! promotion_stack start; then
    echo "Promotion lane failed to start; attempting frozen-lane recovery." >&2
    restore_frozen_after_failure "failed-promotion-start"
    exit 1
  fi
  if ! promotion_stack acceptance; then
    echo "Promotion lane failed runtime acceptance; restoring frozen lane." >&2
    restore_frozen_after_failure "failed-promotion-acceptance"
    exit 1
  fi
  if [[ -e "$PROMOTION_RUNTIME_DIR/lever-pilot-runtime.active" \
     || -e "$PROMOTION_RUNTIME_DIR/lever-pilot-runtime.pending" ]]; then
    echo "Unexpected promotion pilot marker exists after safe startup; restoring frozen lane." >&2
    restore_frozen_after_failure "unexpected-promotion-pilot-marker"
    exit 1
  fi
  if ! promotion_pilot status; then
    echo "Promotion pilot fail-safe status could not be verified; restoring frozen lane." >&2
    restore_frozen_after_failure "failed-promotion-pilot-status"
    exit 1
  fi

  echo "JOBTOMATIK_PROMOTION_LANE_READY_FAIL_SAFE"
  echo "Promotion broker: $PROMOTION_REDIS_URL"
  echo "Open http://127.0.0.1:3000 in Chrome/Opera for the isolated promotion lane."
  echo "No pilot arm, application approval, queue action, or final-submit authority was created by this command."
}

stop_lane() {
  if ! contain_promotion_stack "promotion-stop"; then
    echo "JOBTOMATIK_PROMOTION_LANE_STOP_UNVERIFIED" >&2
    return 1
  fi
  echo "JOBTOMATIK_PROMOTION_LANE_STOPPED"
}

return_frozen() {
  verify_installed_native_contracts
  if ! contain_promotion_stack "before-frozen-return"; then
    echo "Refusing frozen-lane startup because promotion containment is unverified." >&2
    return 1
  fi
  verify_frozen_return_artifact
  frozen_stack start
  frozen_stack acceptance
  echo "JOBTOMATIK_FROZEN_LANE_RESTORED=$EXPECTED_FROZEN_REVISION"
}

status_lane() {
  echo "FROZEN_REPO=$FROZEN_REPO"
  echo "PROMOTION_REPO=$PROMOTION_REPO"
  echo "EXPECTED_FROZEN_REVISION=$EXPECTED_FROZEN_REVISION"
  echo "SOURCE_REVISION_PIN_MODE=$SOURCE_REVISION_PIN_MODE"
  echo "PROMOTION_RUNTIME_DIR=$PROMOTION_RUNTIME_DIR"
  echo "PROMOTION_BROWSER_PROFILE=$PROMOTION_BROWSER_PROFILE"
  echo "PROMOTION_REDIS_URL=$PROMOTION_REDIS_URL"
  if promotion_redis_ready; then
    echo "JOBTOMATIK_PROMOTION_REDIS=READY"
  else
    echo "JOBTOMATIK_PROMOTION_REDIS=DOWN"
  fi
  if [[ -f "$PROMOTION_RUNTIME_DIR/proot-stack.pid" ]]; then
    promotion_stack status || true
  else
    echo "JOBTOMATIK_PROMOTION_LANE_RUNTIME=DOWN"
  fi
  "$PROOT_COMMAND" login "$PROOT_DISTRO" --shared-tmp -- bash -s -- \
    "$PROMOTION_REPO" "$EXPECTED_FROZEN_REVISION" <<'GUEST' || true
set -euo pipefail
repo="$1"
expected_frozen="$2"
marker="$repo/backend/.runtime/promotion-lane.json"
if [[ -f "$marker" ]]; then
  target="$(git -C "$repo" rev-parse HEAD)"
  cd "$repo/backend"
  .venv/bin/python scripts/prepare_lever_promotion_lane_state.py verify \
    --promotion-repo "$repo" \
    --expected-frozen-revision "$expected_frozen" \
    --expected-target-revision "$target"
else
  echo "JOBTOMATIK_PROMOTION_LANE_PREPARED=false"
fi
GUEST
}

if [[ ! "$PROMOTION_REDIS_PORT" =~ ^[0-9]+$ ]] || (( PROMOTION_REDIS_PORT < 1024 || PROMOTION_REDIS_PORT > 65535 )); then
  echo "JOBTOMATIK_PROMOTION_REDIS_PORT must be an unprivileged TCP port." >&2
  exit 2
fi
if [[ ! "$PROMOTION_REDIS_DB" =~ ^[0-9]+$ ]] || (( PROMOTION_REDIS_DB < 0 || PROMOTION_REDIS_DB > 15 )); then
  echo "JOBTOMATIK_PROMOTION_REDIS_DB must be between 0 and 15." >&2
  exit 2
fi
if [[ "$PROMOTION_REDIS_URL" == "$FROZEN_REDIS_URL" ]]; then
  echo "Promotion Redis must not share the frozen runtime broker URL." >&2
  exit 2
fi

require_native_command proot-distro
require_native_command "$STACK_COMMAND"
require_native_command "$PILOT_COMMAND"
require_native_command jobtomatik-browser
require_native_command jobtomatik-pilot-controller
require_native_command jobtomatik-pilot-controller-manager
require_native_command jobtomatik_process_identity.sh
require_native_command redis-server
require_native_command redis-cli
require_native_command sha256sum
PROOT_COMMAND="$(command -v proot-distro)"
STACK_COMMAND="$(command -v "$STACK_COMMAND")"
PILOT_COMMAND="$(command -v "$PILOT_COMMAND")"
BROWSER_COMMAND="$(command -v jobtomatik-browser)"
PILOT_CONTROLLER_COMMAND="$(command -v jobtomatik-pilot-controller)"
PILOT_CONTROLLER_MANAGER_COMMAND="$(command -v jobtomatik-pilot-controller-manager)"
PROCESS_IDENTITY_HELPER="$(command -v jobtomatik_process_identity.sh)"
REDIS_SERVER_BIN="$(command -v redis-server)"
REDIS_CLI_BIN="$(command -v redis-cli)"

resolve_source_revision

case "$ACTION" in
  prepare)
    verify_installed_native_contracts
    prepare_lane
    ;;
  start|prepare-start)
    start_lane
    ;;
  stop)
    stop_lane
    ;;
  return-frozen)
    return_frozen
    ;;
  status)
    status_lane
    ;;
  *)
    echo "Usage: jobtomatik-promotion [prepare|start|prepare-start|stop|return-frozen|status]" >&2
    exit 2
    ;;
esac

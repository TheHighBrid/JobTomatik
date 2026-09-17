#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ACTION="${1:-status}"
PROOT_DISTRO="${JOBTOMATIK_PROOT_DISTRO:-ubuntu}"
FROZEN_REPO="${JOBTOMATIK_FROZEN_PROOT_REPO:-/root/JobTomatik}"
PROMOTION_REPO="${JOBTOMATIK_PROMOTION_PROOT_REPO:-/root/JobTomatik-promotion}"
EXPECTED_FROZEN_REVISION="${JOBTOMATIK_FROZEN_REVISION:-198b197dfcece6fbf9f3edfc5a92511fd951b484}"
STACK_COMMAND="${JOBTOMATIK_STACK_COMMAND:-jobtomatik}"
PILOT_COMMAND="${JOBTOMATIK_PILOT_COMMAND:-jobtomatik-pilot}"
FROZEN_RUNTIME_DIR="${JOBTOMATIK_FROZEN_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"
PROMOTION_RUNTIME_DIR="${JOBTOMATIK_PROMOTION_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-promotion-runtime}"
FROZEN_BROWSER_PROFILE="${JOBTOMATIK_FROZEN_ANDROID_BROWSER_PROFILE:-$HOME/.jobtomatik-chromium}"
PROMOTION_BROWSER_PROFILE="${JOBTOMATIK_PROMOTION_ANDROID_BROWSER_PROFILE:-$HOME/.jobtomatik-promotion-chromium}"
PROMOTION_DEPLOYMENT_MARKER="${JOBTOMATIK_PROMOTION_DEPLOYMENT_RESTART_MARKER:-$PROMOTION_RUNTIME_DIR/deployment-restart.pending}"
NATIVE_TMPDIR="${TMPDIR:-${PREFIX:-/data/data/com.termux/files/usr}/tmp}"
SHARED_CONTROL_DIR="${JOBTOMATIK_SHARED_PILOT_CONTROL_DIR:-$NATIVE_TMPDIR/jobtomatik-pilot-control}"
MIN_FREE_KB="${JOBTOMATIK_PROMOTION_MIN_FREE_KB:-262144}"

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

promotion_stack() {
  JOBTOMATIK_PROOT_REPO="$PROMOTION_REPO" \
  JOBTOMATIK_ANDROID_RUNTIME_DIR="$PROMOTION_RUNTIME_DIR" \
  JOBTOMATIK_ANDROID_BROWSER_PROFILE="$PROMOTION_BROWSER_PROFILE" \
  JOBTOMATIK_DEPLOYMENT_RESTART_MARKER="$PROMOTION_DEPLOYMENT_MARKER" \
    "$STACK_COMMAND" "$@"
}

promotion_pilot() {
  JOBTOMATIK_PROOT_REPO="$PROMOTION_REPO" \
  JOBTOMATIK_ANDROID_RUNTIME_DIR="$PROMOTION_RUNTIME_DIR" \
  JOBTOMATIK_ANDROID_BROWSER_PROFILE="$PROMOTION_BROWSER_PROFILE" \
  JOBTOMATIK_DEPLOYMENT_RESTART_MARKER="$PROMOTION_DEPLOYMENT_MARKER" \
    "$PILOT_COMMAND" "$@"
}

frozen_stack() {
  JOBTOMATIK_PROOT_REPO="$FROZEN_REPO" \
  JOBTOMATIK_ANDROID_RUNTIME_DIR="$FROZEN_RUNTIME_DIR" \
  JOBTOMATIK_ANDROID_BROWSER_PROFILE="$FROZEN_BROWSER_PROFILE" \
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
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -s -- \
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

prepare_lane() {
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -s -- \
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
  (
    cd "$promotion_repo/backend"
    .venv/bin/python scripts/prepare_lever_promotion_lane_state.py verify \
      --promotion-repo "$promotion_repo" \
      --expected-frozen-revision "$expected_frozen" \
      --expected-target-revision "$existing_target"
  )
  echo "JOBTOMATIK_PROMOTION_LANE_ALREADY_PREPARED=$existing_target"
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

start_lane() {
  prepare_lane
  verify_frozen_return_artifact

  promotion_stack stop >/dev/null 2>&1 || true
  frozen_stack stop
  archive_shared_control_dir "$FROZEN_RUNTIME_DIR" "before-promotion"

  if ! promotion_stack start; then
    echo "Promotion lane failed to start; attempting frozen-lane recovery." >&2
    archive_shared_control_dir "$PROMOTION_RUNTIME_DIR" "failed-promotion-start"
    frozen_stack start || true
    exit 1
  fi
  if ! promotion_stack acceptance; then
    echo "Promotion lane failed runtime acceptance; stopping it and restoring frozen lane." >&2
    promotion_stack stop || true
    archive_shared_control_dir "$PROMOTION_RUNTIME_DIR" "failed-promotion-acceptance"
    frozen_stack start || true
    exit 1
  fi

  if [[ -e "$PROMOTION_RUNTIME_DIR/lever-pilot-runtime.active" \
     || -e "$PROMOTION_RUNTIME_DIR/lever-pilot-runtime.pending" ]]; then
    echo "Unexpected promotion pilot marker exists after safe startup; containing runtime." >&2
    promotion_stack stop || true
    exit 1
  fi

  promotion_pilot status || {
    echo "Promotion pilot fail-safe status could not be verified; containing runtime." >&2
    promotion_stack stop || true
    exit 1
  }

  echo "JOBTOMATIK_PROMOTION_LANE_READY_FAIL_SAFE"
  echo "Open http://127.0.0.1:3000 in Chrome/Opera for the isolated promotion lane."
  echo "No pilot arm, application approval, queue action, or final-submit authority was created by this command."
}

stop_lane() {
  promotion_stack stop || true
  archive_shared_control_dir "$PROMOTION_RUNTIME_DIR" "promotion-stop"
  echo "JOBTOMATIK_PROMOTION_LANE_STOPPED"
}

return_frozen() {
  promotion_stack stop || true
  archive_shared_control_dir "$PROMOTION_RUNTIME_DIR" "before-frozen-return"
  verify_frozen_return_artifact
  frozen_stack start
  frozen_stack acceptance
  echo "JOBTOMATIK_FROZEN_LANE_RESTORED=$EXPECTED_FROZEN_REVISION"
}

status_lane() {
  echo "FROZEN_REPO=$FROZEN_REPO"
  echo "PROMOTION_REPO=$PROMOTION_REPO"
  echo "EXPECTED_FROZEN_REVISION=$EXPECTED_FROZEN_REVISION"
  echo "PROMOTION_RUNTIME_DIR=$PROMOTION_RUNTIME_DIR"
  echo "PROMOTION_BROWSER_PROFILE=$PROMOTION_BROWSER_PROFILE"
  if [[ -f "$PROMOTION_RUNTIME_DIR/proot-stack.pid" ]]; then
    promotion_stack status || true
  else
    echo "JOBTOMATIK_PROMOTION_LANE_RUNTIME=DOWN"
  fi
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -s -- \
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

require_native_command proot-distro
require_native_command "$STACK_COMMAND"
require_native_command "$PILOT_COMMAND"

case "$ACTION" in
  prepare)
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

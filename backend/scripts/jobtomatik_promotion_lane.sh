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
actual="$(git -C "$repo" rev-parse HEAD | tr '[:upper:]' '[:lower:]')"
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
    "$FROZEN_REPO" "$PROMOTION_REPO" "$EXPECTED_FROZEN_REVISION" "$MIN_FREE_KB" <<'GUEST'
set -euo pipefail

source_repo="$1"
promotion_repo="$2"
expected_frozen="$3"
min_free_kb="$4"
marker_rel="backend/.runtime/promotion-lane.json"
promotion_db_name="jobtomatik-promotion.db"

if [[ ! -d "$source_repo/.git" && ! -f "$source_repo/.git" ]]; then
  echo "Frozen repository is not a Git checkout: $source_repo" >&2
  exit 1
fi

source_head="$(git -C "$source_repo" rev-parse HEAD | tr '[:upper:]' '[:lower:]')"
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
target_revision="$(git -C "$source_repo" rev-parse origin/main | tr '[:upper:]' '[:lower:]')"

# Sharing the existing Python environment saves device storage. It is permitted only
# while the exact dependency lock represented by requirements.txt is unchanged.
source_requirements="$(git -C "$source_repo" rev-parse "$source_head:backend/requirements.txt")"
target_requirements="$(git -C "$source_repo" rev-parse "$target_revision:backend/requirements.txt")"
if [[ "$source_requirements" != "$target_requirements" ]]; then
  echo "backend/requirements.txt changed since the frozen runtime; refusing to share its virtualenv." >&2
  exit 1
fi

# Native commands remain installed from the frozen runtime. Prove that the scripts
# those commands came from are byte-identical on the promotion revision before reuse.
for path in \
  backend/scripts/jobtomatik_termux_wrapper.sh \
  backend/scripts/jobtomatik_pilot_wrapper.sh \
  backend/scripts/jobtomatik_pilot_control_daemon.sh \
  backend/scripts/jobtomatik_pilot_controller_manager.sh \
  backend/scripts/start_android_browser_cdp.sh \
  backend/scripts/jobtomatik_process_identity.sh; do
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
  "$source_repo/backend/.venv/bin/python" - "$promotion_repo" "$expected_frozen" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
expected_frozen = sys.argv[2]
marker_path = repo / "backend/.runtime/promotion-lane.json"
marker = json.loads(marker_path.read_text(encoding="utf-8"))
if marker.get("source_frozen_revision") != expected_frozen:
    raise SystemExit("Existing promotion lane was not derived from the expected frozen runtime")
db = repo / "backend" / str(marker.get("promotion_database") or "")
if not db.is_file():
    raise SystemExit("Existing promotion lane database is missing")
with sqlite3.connect(db) as connection:
    result = connection.execute("PRAGMA quick_check").fetchone()
if not result or result[0] != "ok":
    raise SystemExit("Existing promotion lane database failed quick_check")
print(f"JOBTOMATIK_PROMOTION_LANE_ALREADY_PREPARED={marker.get('target_revision')}")
PY
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

"$source_repo/backend/.venv/bin/python" - \
  "$source_repo" "$promotion_repo" "$source_head" "$target_revision" "$promotion_db_name" <<'PY'
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

source_repo = Path(sys.argv[1]).resolve()
promotion_repo = Path(sys.argv[2]).resolve()
source_revision = sys.argv[3]
target_revision = sys.argv[4]
promotion_db_name = sys.argv[5]
source_backend = source_repo / "backend"
promotion_backend = promotion_repo / "backend"
source_env = source_backend / ".env"
promotion_env = promotion_backend / ".env"


def read_env_value(path: Path, key: str) -> str | None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    return None


def set_env_value(lines: list[str], key: str, value: str) -> list[str]:
    prefix = f"{key}="
    updated = []
    replaced = False
    for raw in lines:
        if raw.startswith(prefix):
            if not replaced:
                updated.append(f"{key}={value}")
                replaced = True
            continue
        updated.append(raw)
    if not replaced:
        if updated and updated[-1] != "":
            updated.append("")
        updated.append(f"{key}={value}")
    return updated


database_url = read_env_value(source_env, "DATABASE_URL") or "sqlite:///./jobtomatik.db"
url = make_url(database_url)
if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
    raise SystemExit("Promotion lane requires the physical Android runtime to use a file-backed SQLite database")
source_db = Path(url.database)
if not source_db.is_absolute():
    source_db = (source_backend / source_db).resolve()
if not source_db.is_file():
    raise SystemExit(f"Frozen SQLite database is missing: {source_db}")

target_db = promotion_backend / promotion_db_name
if target_db.exists():
    raise SystemExit(f"Refusing to overwrite existing promotion database: {target_db}")

# sqlite3.Connection.backup is WAL-aware and produces a consistent point-in-time
# snapshot without mutating the frozen database, even while the frozen runtime is live.
source_uri = f"file:{source_db}?mode=ro"
with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(target_db) as target:
    source.backup(target)
    check = target.execute("PRAGMA quick_check").fetchone()
if not check or check[0] != "ok":
    target_db.unlink(missing_ok=True)
    raise SystemExit("Promotion database snapshot failed SQLite quick_check")

shutil.copy2(source_env, promotion_env)
lines = promotion_env.read_text(encoding="utf-8").splitlines()
safe_values = {
    "DATABASE_URL": f"sqlite:///./{promotion_db_name}",
    "ALLOW_REAL_APPLICATION_SUBMIT": "false",
    "ALLOW_REAL_FOLLOWUP_SEND": "false",
    "AUTOPILOT_ENABLED": "false",
    "GREENHOUSE_SUPERVISED_PILOT_ENABLED": "false",
    "LEVER_SUPERVISED_PILOT_ENABLED": "false",
}
for key, value in safe_values.items():
    lines = set_env_value(lines, key, value)
promotion_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
promotion_env.chmod(0o600)

# Preserve files referenced by the copied database without sharing writable inodes
# back into the frozen certification lane.
for relative in (Path("backend/uploads"), Path("backend/handoff_sessions"), Path("handoff_sessions")):
    source = source_repo / relative
    destination = promotion_repo / relative
    if source.is_dir() and not destination.exists():
        shutil.copytree(source, destination)

runtime_dir = promotion_backend / ".runtime"
runtime_dir.mkdir(parents=True, exist_ok=True)
sha = hashlib.sha256()
with target_db.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        sha.update(chunk)
marker = {
    "version": 1,
    "lane": "lever_promotion_evidence",
    "source_frozen_revision": source_revision,
    "target_revision": target_revision,
    "promotion_database": promotion_db_name,
    "promotion_database_sha256": sha.hexdigest(),
    "prepared_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "safety_flags": safe_values,
    "browser_profile_policy": "separate_native_profile_required",
    "final_submit_authority_created": False,
}
(runtime_dir / "promotion-lane.json").write_text(
    json.dumps(marker, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(marker, sort_keys=True))
PY

created=0
trap - ERR INT TERM HUP
echo "JOBTOMATIK_PROMOTION_LANE_PREPARED=$target_revision"
GUEST
}

start_lane() {
  prepare_lane
  # Prove that the frozen lane can be restarted from its already-installed exact
  # static artifact before stopping anything. This prevents a one-way lane switch.
  verify_frozen_return_artifact

  # Stop both known lane identities before clearing the one shared /tmp request bus.
  # Each stop command is identity-bound to its own runtime dir/profile and refuses to
  # signal unrelated processes.
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
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -s -- "$PROMOTION_REPO" <<'GUEST' || true
set -euo pipefail
repo="$1"
marker="$repo/backend/.runtime/promotion-lane.json"
if [[ -f "$marker" ]]; then
  cat "$marker"
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
  start)
    start_lane
    ;;
  prepare-start)
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

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

checkout_status="$(git status --porcelain=v1 --untracked-files=all)"
if [[ -n "$checkout_status" ]]; then
  echo "The Phase 0 integration proof requires a clean committed checkout" >&2
  exit 2
fi
command -v docker >/dev/null || { echo "Docker is required for the Phase 0 Compose proof" >&2; exit 2; }

export JOBTOMATIK_RUNTIME_REVISION="$(git rev-parse HEAD)"
mkdir -p "$ROOT_DIR/verification-artifacts"
export ONEHOST_EVIDENCE_DIR="$(mktemp -d "$ROOT_DIR/verification-artifacts/onehost-api-celery.XXXXXX")"
project="jt-phase0-api-celery-${GITHUB_RUN_ID:-local}-$$"
source_dir="$(mktemp -d)"
compose=(docker compose --env-file /dev/null --project-name "$project"
  --project-directory "$source_dir" --file "$source_dir/docker-compose.onehost-api-celery.yml")
host_uid="$(id -u)"
host_gid="$(id -g)"
started=false
ownership_restored=false
source_sha256=""

restore_evidence_owner() {
  "${compose[@]}" run --rm --no-deps -T --entrypoint python proof - "$host_uid" "$host_gid" <<'PY'
import os
import sys

uid, gid = int(sys.argv[1]), int(sys.argv[2])
for root, directories, files in os.walk('/evidence', followlinks=False):
    for name in directories + files:
        os.chown(os.path.join(root, name), uid, gid, follow_symlinks=False)
os.chown('/evidence', uid, gid, follow_symlinks=False)
PY
}

stamp_summary_provenance() {
  local summary_path="$ONEHOST_EVIDENCE_DIR/proof/summary.json"
  if [[ -z "$source_sha256" || ! -f "$summary_path" ]]; then
    return 0
  fi
  python - "$summary_path" "$JOBTOMATIK_RUNTIME_REVISION" "$source_sha256" <<'PY'
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
revision = sys.argv[2]
source_sha256 = sys.argv[3]
summary = json.loads(summary_path.read_text(encoding="utf-8"))
if summary.get("repository_revision") != revision:
    raise SystemExit("Phase 0 summary revision does not match the executed checkout")
summary["source_sha256"] = source_sha256
summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
PY
}

record_teardown() {
  local fixture_container_id="$1"
  local compose_down_succeeded="$2"
  local project_query_succeeded="$3"
  local remaining_project_containers="$4"
  local fixture_running_after_down="$5"
  python - \
    "$ONEHOST_EVIDENCE_DIR/teardown.json" \
    "$fixture_container_id" \
    "$compose_down_succeeded" \
    "$project_query_succeeded" \
    "$remaining_project_containers" \
    "$fixture_running_after_down" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
fixture_container_id = sys.argv[2]
compose_down_succeeded = sys.argv[3] == "true"
project_query_succeeded = sys.argv[4] == "true"
remaining = [item for item in sys.argv[5].split() if item]
fixture_running_after_down = sys.argv[6] == "true"
cleanup_verified = (
    project_query_succeeded
    and not remaining
    and not fixture_running_after_down
)
path.write_text(
    json.dumps(
        {
            "fixture_container_id": fixture_container_id or None,
            "compose_down_succeeded": compose_down_succeeded,
            "project_container_query_succeeded": project_query_succeeded,
            "remaining_project_containers": remaining,
            "fixture_running_after_down": fixture_running_after_down,
            "cleanup_verified": cleanup_verified,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
if not cleanup_verified:
    raise SystemExit(1)
PY
}

cleanup() {
  local status=$?
  local fixture_container_id=""
  local compose_down_succeeded=true
  local project_query_succeeded=true
  local remaining_project_containers=""
  local fixture_running_after_down=false

  if [[ "$started" == true ]]; then
    "${compose[@]}" logs --no-color backend > "$ONEHOST_EVIDENCE_DIR/backend.log" 2>&1 || true
    "${compose[@]}" logs --no-color celery_worker > "$ONEHOST_EVIDENCE_DIR/celery-worker.log" 2>&1 || true
    "${compose[@]}" logs --no-color fixture > "$ONEHOST_EVIDENCE_DIR/fixture.log" 2>&1 || true
    fixture_container_id="$("${compose[@]}" ps -q fixture 2>/dev/null || true)"
    if [[ "$ownership_restored" != true ]]; then
      if restore_evidence_owner; then
        ownership_restored=true
      else
        echo "Could not restore synthetic artifact ownership" >&2
        status=1
      fi
    fi
    stamp_summary_provenance || { echo "Could not retain Phase 0 source provenance" >&2; status=1; }
  fi

  if ! "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1; then
    compose_down_succeeded=false
  fi

  if [[ "$started" == true ]]; then
    if ! remaining_project_containers="$(docker ps -aq --filter "label=com.docker.compose.project=$project" 2>/dev/null)"; then
      project_query_succeeded=false
      remaining_project_containers=""
    fi
    if [[ -n "$fixture_container_id" ]]; then
      fixture_running_after_down="$(
        docker inspect --format '{{.State.Running}}' "$fixture_container_id" 2>/dev/null || printf 'false'
      )"
    fi
    record_teardown \
      "$fixture_container_id" \
      "$compose_down_succeeded" \
      "$project_query_succeeded" \
      "$remaining_project_containers" \
      "$fixture_running_after_down" \
      || { echo "Phase 0 fixture/container cleanup was not verified" >&2; status=1; }
  fi

  rm -rf -- "$source_dir"
  exit "$status"
}
trap cleanup EXIT

# Execute a Git-only snapshot so ignored or uncommitted local files cannot alter
# the proof. The host wrapper itself is included in the retained object manifest.
git archive --format=tar "$JOBTOMATIK_RUNTIME_REVISION" backend docker-compose.onehost-api-celery.yml \
  | tar -xf - -C "$source_dir"
git ls-tree -r "$JOBTOMATIK_RUNTIME_REVISION" -- \
  backend/app/onehost_phase0_worker.py \
  backend/app/services/onehost_phase0_fixture_runtime.py \
  backend/scripts/probe_onehost_phase0_redirect.py \
  backend/scripts/run_onehost_api_celery_gate.py \
  backend/tests/fixtures/onehost_http_form.html \
  docker-compose.onehost-api-celery.yml \
  scripts/verify-onehost-api-celery.sh \
  .github/workflows/onehost-api-celery-gate.yml \
  > "$ONEHOST_EVIDENCE_DIR/committed-inputs.txt"

source_sha256="$(
  python - "$source_dir/backend" <<'PY'
import hashlib
import sys
from pathlib import Path

backend_root = Path(sys.argv[1])
paths = sorted((backend_root / "app").rglob("*.py")) + [
    backend_root / "scripts/probe_onehost_phase0_redirect.py",
    backend_root / "scripts/run_onehost_api_celery_gate.py",
    backend_root / "tests/fixtures/onehost_http_form.html",
]
digest = hashlib.sha256()
for path in paths:
    digest.update(str(path.relative_to(backend_root)).encode() + b"\0")
    digest.update(path.read_bytes() + b"\0")
print(digest.hexdigest())
PY
)"
printf '%s\n' "$source_sha256" > "$ONEHOST_EVIDENCE_DIR/source-sha256.txt"

"${compose[@]}" config --format json > "$ONEHOST_EVIDENCE_DIR/compose.json"
"${compose[@]}" build 2>&1 | tee "$ONEHOST_EVIDENCE_DIR/build.log"
started=true

# `proof` is the only expected terminating service. Its three iterations each
# cross FastAPI -> Redis -> Celery -> submit_application_task -> owned Chromium.
"${compose[@]}" up --abort-on-container-exit --exit-code-from proof proof \
  2>&1 | tee "$ONEHOST_EVIDENCE_DIR/proof.log"

# Reuse the exact production proof guard in a hostile local redirect scenario.
# The destination server runs inside this synthetic probe and must receive zero requests.
"${compose[@]}" run --rm --no-deps -T proof \
  python -m scripts.probe_onehost_phase0_redirect \
  --output /evidence/redirect-negative-control.json \
  2>&1 | tee "$ONEHOST_EVIDENCE_DIR/redirect-negative-control.log"

restore_evidence_owner
ownership_restored=true
stamp_summary_provenance

python - \
  "$ONEHOST_EVIDENCE_DIR/proof/summary.json" \
  "$ONEHOST_EVIDENCE_DIR/redirect-negative-control.json" \
  "$JOBTOMATIK_RUNTIME_REVISION" \
  "$source_sha256" <<'PY'
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
redirect_path = Path(sys.argv[2])
revision = sys.argv[3]
source_sha256 = sys.argv[4]
summary = json.loads(summary_path.read_text(encoding='utf-8'))
redirect = json.loads(redirect_path.read_text(encoding='utf-8'))
assert summary['status'] == 'passed', summary
assert summary['api_celery_dispatch_proven'] is True, summary
assert summary['employer_certification'] is False, summary
assert summary['repository_revision'] == revision, summary
assert summary['source_sha256'] == source_sha256 and len(source_sha256) == 64, summary
assert len(summary['runs']) >= 3, summary
assert len({item['application_id'] for item in summary['runs']}) == len(summary['runs']), summary
assert len({item['task_id'] for item in summary['runs']}) == len(summary['runs']), summary
assert all(item['status'] == 'passed' for item in summary['runs']), summary
assert redirect['status'] == 'passed', redirect
assert redirect['checks']['redirect_was_explicitly_blocked'] is True, redirect
assert redirect['checks']['redirect_destination_was_never_requested'] is True, redirect
assert redirect['checks']['browser_observed_no_escape'] is True, redirect
assert redirect['redirect_destination_hits'] == 0, redirect
print(json.dumps(summary, indent=2))
print(json.dumps(redirect, indent=2))
PY

printf 'Phase 0 API/Celery proof and traces: %s\n' "$ONEHOST_EVIDENCE_DIR"

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

cleanup() {
  local status=$?
  if [[ "$started" == true ]]; then
    "${compose[@]}" logs --no-color backend > "$ONEHOST_EVIDENCE_DIR/backend.log" 2>&1 || true
    "${compose[@]}" logs --no-color celery_worker > "$ONEHOST_EVIDENCE_DIR/celery-worker.log" 2>&1 || true
    "${compose[@]}" logs --no-color fixture > "$ONEHOST_EVIDENCE_DIR/fixture.log" 2>&1 || true
    restore_evidence_owner || { echo "Could not restore synthetic artifact ownership" >&2; status=1; }
  fi
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
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
  backend/scripts/run_onehost_api_celery_gate.py \
  backend/tests/fixtures/onehost_http_form.html \
  docker-compose.onehost-api-celery.yml \
  scripts/verify-onehost-api-celery.sh \
  .github/workflows/onehost-api-celery-gate.yml \
  > "$ONEHOST_EVIDENCE_DIR/committed-inputs.txt"

"${compose[@]}" config --format json > "$ONEHOST_EVIDENCE_DIR/compose.json"
"${compose[@]}" build 2>&1 | tee "$ONEHOST_EVIDENCE_DIR/build.log"
started=true

# `proof` is the only expected terminating service. Its three iterations each
# cross FastAPI -> Redis -> Celery -> submit_application_task -> owned Chromium.
"${compose[@]}" up --abort-on-container-exit --exit-code-from proof proof \
  2>&1 | tee "$ONEHOST_EVIDENCE_DIR/proof.log"

python - "$ONEHOST_EVIDENCE_DIR/proof/summary.json" "$JOBTOMATIK_RUNTIME_REVISION" <<'PY'
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
revision = sys.argv[2]
summary = json.loads(summary_path.read_text(encoding='utf-8'))
assert summary['status'] == 'passed', summary
assert summary['api_celery_dispatch_proven'] is True, summary
assert summary['employer_certification'] is False, summary
assert summary['repository_revision'] == revision, summary
assert len(summary['runs']) >= 3, summary
assert all(item['status'] == 'passed' for item in summary['runs']), summary
print(json.dumps(summary, indent=2))
PY

printf 'Phase 0 API/Celery proof and traces: %s\n' "$ONEHOST_EVIDENCE_DIR"

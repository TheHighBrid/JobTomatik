#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
fixture_checkout_status="$(git status --porcelain=v1 --untracked-files=all)"
if [[ -n "$fixture_checkout_status" ]]; then
  echo "The proof requires a clean committed checkout; commit or remove working-tree changes first" >&2
  exit 2
fi
command -v docker >/dev/null || { echo "Docker is required for the Compose proof" >&2; exit 2; }
export JOBTOMATIK_RUNTIME_REVISION="$(git rev-parse HEAD)"
mkdir -p "$ROOT_DIR/verification-artifacts"
export ONEHOST_EVIDENCE_DIR="$(mktemp -d "$ROOT_DIR/verification-artifacts/onehost-fixture.XXXXXX")"
fixture_project="jt-onehost-${GITHUB_RUN_ID:-local}-$$"
fixture_source_dir="$(mktemp -d)"
compose=(docker compose --env-file /dev/null --project-name "$fixture_project"
  --project-directory "$fixture_source_dir" --file "$fixture_source_dir/docker-compose.onehost-fixture.yml")
fixture_host_uid="$(id -u)"
fixture_host_gid="$(id -g)"
fixture_container_started=false
restore_evidence_owner() {
  # pytest deliberately creates private directories. Give these synthetic
  # artifacts back to the host uploader, without widening their permissions.
  "${compose[@]}" run --rm -T backend python - "$fixture_host_uid" "$fixture_host_gid" <<'PY'
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
  local fixture_exit_status=$?
  if [[ "$fixture_container_started" == true ]]; then
    restore_evidence_owner || { echo "Could not restore synthetic artifact ownership" >&2; fixture_exit_status=1; }
  fi
  "${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "$fixture_source_dir"
  exit "$fixture_exit_status"
}
trap cleanup EXIT

# Build the committed snapshot, excluding even Git-ignored local files that
# Docker's ignore rules might otherwise admit into the execution context.
git archive --format=tar "$JOBTOMATIK_RUNTIME_REVISION" backend docker-compose.onehost-fixture.yml \
  | tar -xf - -C "$fixture_source_dir"
git ls-tree -r "$JOBTOMATIK_RUNTIME_REVISION" -- backend docker-compose.onehost-fixture.yml \
  scripts/verify-onehost-fixture.sh .github/workflows/onehost-fixture-gate.yml \
  > "$ONEHOST_EVIDENCE_DIR/committed-inputs.txt"
"${compose[@]}" config --format json > "$ONEHOST_EVIDENCE_DIR/compose.json"
"${compose[@]}" build backend 2>&1 | tee "$ONEHOST_EVIDENCE_DIR/build.log"
fixture_container_started=true
"${compose[@]}" run --rm -T backend python -m pytest -q \
  --basetemp /evidence/test-runs --junitxml /evidence/pytest.xml \
  tests/test_onehost_fixture_gate.py tests/test_ats_flow_safety.py \
  tests/test_control_engine_playwright.py 2>&1 | tee "$ONEHOST_EVIDENCE_DIR/tests.log"
"${compose[@]}" run --rm -T backend 2>&1 | tee "$ONEHOST_EVIDENCE_DIR/proof.log"
printf 'Fixture proof and traces: %s\n' "$ONEHOST_EVIDENCE_DIR"
